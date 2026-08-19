"""The generate loop: tailor -> ground -> render -> verify -> score, retrying with the
reasons attached.

    profile.yaml ─┐
                  ├─→ tailor ─→ ground ─→ score ─→ render ─→ verify ─→ out/
    evidence.json ┤                 ↑        │        │
                  │                 └────────┴────────┘
    job_desc.txt ─┘        retry with violations + gaps

Three rules make the loop worth having rather than just expensive:

  1. A rejection costs what it should cost, and no more. A draft that fails grounding is
     first repaired — the unsupportable parts are cut out and the remainder goes back
     through the same gate — because one bad token in one bullet is not a reason to throw
     away the other fifteen and an LLM call with them. Only a draft with nothing
     supportable left in it is dropped, and that one is never rendered: launching Chromium
     for claims that are about to be rejected wastes a second per iteration and produces an
     artefact nobody should look at.

  2. What gets cut is fed back anyway. A repaired document is grounded but smaller, and the
     next attempt should be one that needs no cutting.

  3. The best attempt is kept, not the last one. Iteration 4 can score worse than
     iteration 2 — the feedback pushes on gaps, and pushing can cost coverage elsewhere —
     and silently shipping the final draft would make more iterations actively harmful. At
     equal score an untouched draft beats a repaired one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import ats, ground, letter_review, runrecord
from . import report as report_module
from . import score as score_module
from .config import Settings
from .document import CoverLetter, ResumeDoc
from .evidence import Corpus
from .jd import JobDescription
from .llm import LLMCall
from .meter import Meter
from .profile import Profile
from .progress import (
    CANCELLED,
    DONE,
    GROUNDING,
    REJECTED,
    RENDERING,
    REPAIRED,
    SCORED,
    SCORING,
    TAILORING,
    VERIFYING,
    WRITING_REPORT,
    Cancelled,
    Progress,
)
from .render import Rendered, render_cover_letter, render_resume
from .score import Ceiling, Score
from .source import SourceIndex
from .verify import VerifyReport, verify, verify_letter


@dataclass
class Attempt:
    number: int
    doc: ResumeDoc
    violations: list[ground.Violation] = field(default_factory=list)
    # Set when the draft failed the gate and removing the failing parts left a document
    # that passes it. `doc` stays as the model wrote it; `document` is what got rendered.
    repair: ground.Repair | None = None
    score: Score | None = None
    verify_report: VerifyReport | None = None
    rendered: Rendered | None = None
    review: ats.AtsReport | None = None

    @property
    def document(self) -> ResumeDoc:
        """What was actually rendered and scored."""
        return self.repair.doc if self.repair is not None else self.doc

    @property
    def grounded(self) -> bool:
        """True of the *rendered* document. A repaired one is grounded in the full sense —
        it went through check() a second time and came back clean."""
        return not self.violations

    @property
    def repaired(self) -> bool:
        return self.repair is not None

    @property
    def total(self) -> float:
        return self.score.total if self.score else -1.0

    def rank(self) -> tuple:
        """Grounded beats ungrounded; parsing beats not parsing; then the score; and an
        untouched draft beats a repaired one that scored the same, because the repaired one
        is the same document with something cut out of it."""
        return (
            self.grounded,
            bool(self.verify_report and self.verify_report.ok),
            self.total,
            not self.repaired,
        )

    def note(self) -> str:
        if self.violations:
            return f"rejected by the grounding gate ({ground.summarize(self.violations)})"
        parts = [f"score {self.total:.1f}"]
        if self.repair is not None:
            parts.append(f"repaired: dropped {self.repair.summary()}")
        if self.verify_report:
            parts.append("PDF parses" if self.verify_report.ok else "PDF failed its checks")
            parts.append(f"{self.verify_report.page_count} page(s)")
        return ", ".join(parts)


# Why the loop stopped. Recorded rather than inferred: "4 iterations" and "1 iteration"
# look identical in a report unless it says which of these happened, and they mean opposite
# things about whether spending more would have helped.
STOP_REASONS = {
    "threshold": "the score reached the threshold",
    "ceiling": "the score reached what this record can reach for this posting",
    "plateau": "another rewrite stopped buying anything",
    "exhausted": "the iteration budget ran out",
    "ungrounded": "no draft survived the grounding gate",
    "cancelled": "the run was cancelled",
}


@dataclass
class RunResult:
    out_dir: Path
    attempts: list[Attempt]
    best: Attempt
    report_path: Path
    blocked_terms: list[str]
    threshold: float
    cancelled: bool = False
    # What this record could reach for this posting, and how close counts as arrival.
    ceiling: Ceiling | None = None
    slack: float = 2.0
    stop_reason: str = "exhausted"

    @property
    def ok(self) -> bool:
        """Grounded and parses. The score not clearing the threshold is not a failure —
        it is the honest answer (PLAN.md open question 5)."""
        return self.best.grounded and bool(self.best.verify_report and self.best.verify_report.ok)

    @property
    def met_threshold(self) -> bool:
        return self.best.total >= self.threshold

    @property
    def reachable(self) -> float:
        """The highest score this record could have got for this posting."""
        return self.ceiling.total if self.ceiling else 100.0

    @property
    def at_ceiling(self) -> bool:
        """The loop got everything out of the record that was there to get.

        This is the number that means something when the threshold was never reachable, and
        it is a success rather than the failure "below threshold" reads as.
        """
        return self.ceiling is not None and self.best.total >= self.ceiling.total - self.slack

    @property
    def threshold_reachable(self) -> bool:
        return self.ceiling is None or self.ceiling.is_reachable(self.threshold)

    def why_stopped(self) -> str:
        return STOP_REASONS.get(self.stop_reason, self.stop_reason)


def run_dir(jd: JobDescription, cfg: Settings, *, today: date | None = None) -> Path:
    stamp = (today or date.today()).isoformat()
    name = "-".join(p for p in (jd.run_slug, stamp) if p) or stamp
    return cfg.OUT_DIR / name


def source_index(profile: Profile, corpus: Corpus | None) -> SourceIndex:
    index = profile.sources()
    if corpus:
        index.update(corpus.sources())
    return index


def generate(
    profile: Profile,
    jd: JobDescription,
    corpus: Corpus | None,
    cfg: Settings,
    llm_call: LLMCall,
    *,
    out_dir: Path,
    progress: Progress | None = None,
    write_report: bool = True,
) -> RunResult:
    from .tailor import tailor

    index = source_index(profile, corpus)
    report = progress or Progress()

    attempts: list[Attempt] = []
    blocked: list[str] = []
    feedback = ""
    cancelled = False
    out_dir.mkdir(parents=True, exist_ok=True)
    total = max(1, cfg.MAX_ITER)
    # Computed once, before any model call: it depends only on the record and the posting.
    limit = score_module.ceiling(profile, jd, index)
    stop_reason = ""
    previous_best = -1.0

    for number in range(1, total + 1):
        where = {"document": "resume", "attempt": number, "attempts": total}
        repair_feedback = ""
        try:
            report(TAILORING, **where)
            doc = tailor(
                profile, jd, corpus, llm_call, max_pages=cfg.RESUME_MAX_PAGES, feedback=feedback,
                extra_rules=ats.TAILOR_RULES,
            )
            attempt = Attempt(number=number, doc=doc)

            report(GROUNDING, **where)
            attempt.violations = ground.check(doc, profile, index)
            attempts.append(attempt)

            if attempt.violations:
                blocked = list(dict.fromkeys(blocked + ground.unsupported_terms(attempt.violations)))
                # A rejection used to end the iteration here, throwing away every bullet in
                # the draft over whichever one could not be supported. Cut the failing parts
                # out instead and see whether what is left still passes the same gate.
                salvaged = ground.repair(doc, profile, index, attempt.violations)
                if not salvaged.ok:
                    feedback = ground.feedback(attempt.violations)
                    report(REJECTED, **where, reason=ground.summarize(attempt.violations))
                    continue
                attempt.repair = salvaged
                attempt.violations = []
                # Still fed back: the next attempt should write a document that does not
                # need cutting, and the removed bullets are the specific reason why.
                repair_feedback = ground.feedback(salvaged.dropped)
                report(REPAIRED, **where, reason=salvaged.summary(), dropped=len(salvaged.dropped))

            rendered_doc = attempt.document

            report(RENDERING, **where)
            attempt.rendered = render_resume(rendered_doc, profile, out_dir, cfg)

            report(VERIFYING, **where)
            attempt.verify_report = verify(
                attempt.rendered.pdf_path, rendered_doc, profile,
                max_pages=cfg.RESUME_MAX_PAGES, page_count=attempt.rendered.page_count,
            )

            report(SCORING, **where)
            # Built here rather than inside score(): the parsing half of the rubric needs the
            # rendered HTML and the real page count, and neither is knowable from the
            # document alone.
            attempt.review = ats.review(
                rendered_doc, profile,
                html=attempt.rendered.html_path.read_text(encoding="utf-8"),
                page_count=attempt.rendered.page_count,
                max_pages=cfg.RESUME_MAX_PAGES,
            )
            attempt.score = score_module.score(
                rendered_doc, profile, jd, index, attempt.verify_report, attempt.review
            )
            report(
                SCORED, **where, score=attempt.score.total,
                parses=attempt.verify_report.ok, pages=attempt.verify_report.page_count,
            )
        except Cancelled:
            cancelled = True
            # Nothing finished, so there is no partial result worth describing. Let run()
            # record a cancelled run rather than inventing an empty one here.
            if not attempts:
                raise
            break

        stop_reason = _stop_reason(attempt, previous_best, limit, cfg)
        previous_best = max(previous_best, attempt.total)
        if stop_reason:
            break
        feedback = "\n\n".join(
            part
            for part in (
                repair_feedback,
                ats.feedback(attempt.review) if attempt.review else "",
                score_module.feedback(
                    attempt.score, min(cfg.SCORE_THRESHOLD, limit.total), attempt.verify_report
                ),
            )
            if part
        )

    best = max(attempts, key=lambda a: a.rank())
    if not stop_reason:
        stop_reason = (
            "cancelled" if cancelled else "ungrounded" if not best.grounded else "exhausted"
        )

    # The last attempt rendered is the one sitting on disk. If it was not the best one,
    # render the best again so the PDF matches the report that describes it.
    if best.grounded and best is not attempts[-1]:
        best.rendered = render_resume(best.document, profile, out_dir, cfg)
        best.verify_report = verify(
            best.rendered.pdf_path, best.document, profile,
            max_pages=cfg.RESUME_MAX_PAGES, page_count=best.rendered.page_count,
        )

    # The rendered document, not the drafted one: if repair cut a bullet, resume.json has to
    # match the PDF sitting next to it or a diff of two runs compares fiction.
    (out_dir / "resume.json").write_text(
        json.dumps(best.document.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    result = RunResult(
        out_dir=out_dir, attempts=attempts, best=best, report_path=out_dir / "report.md",
        blocked_terms=blocked, threshold=cfg.SCORE_THRESHOLD, cancelled=cancelled,
        ceiling=limit, slack=cfg.CEILING_SLACK, stop_reason=stop_reason,
    )
    if write_report:
        # `run()` writes a combined report when a cover letter is in play, so it asks for
        # this to be skipped rather than having it written twice.
        result.report_path.write_text(
            resume_report(result, profile, jd, index, cfg), encoding="utf-8"
        )
    return result


def _stop_reason(attempt: Attempt, previous_best: float, limit: Ceiling, cfg: Settings) -> str:
    """Is there any point in another iteration? Empty string means yes.

    Three ways to be finished, and the second and third are the ones that were missing. The
    threshold alone is a rule the loop frequently *cannot* satisfy: it is a fixed number, and
    what a record can reach against a posting is not. A run that wants 80, tops out at 64,
    and spends four model calls discovering that on every attempt has learned nothing after
    the first one — and ground.py is what guarantees it could never have done better, which
    is exactly why stopping there is honest rather than lazy.
    """
    if attempt.score is None or attempt.verify_report is None or not attempt.verify_report.ok:
        # A PDF that does not parse is worth another attempt regardless of its score: that
        # is the one thing this tool actually promises.
        return ""
    if attempt.score.total >= cfg.SCORE_THRESHOLD:
        return "threshold"
    if attempt.score.total >= limit.total - cfg.CEILING_SLACK:
        return "ceiling"
    if previous_best >= 0 and attempt.score.total - previous_best < cfg.MIN_GAIN:
        return "plateau"
    return ""


def resume_report(
    result: RunResult, profile: Profile, jd: JobDescription, index: SourceIndex, cfg: Settings,
    meter: Meter | None = None,
) -> str:
    best = result.best
    return report_module.build(
        doc=best.document, profile=profile, jd=jd, index=index,
        removed=best.repair.notes() if best.repair else [],
        score=best.score or score_module.score(best.document, profile, jd, index),
        review=best.review,
        verify_report=best.verify_report, iterations=len(result.attempts),
        threshold=cfg.SCORE_THRESHOLD, blocked_terms=result.blocked_terms,
        violations=best.violations,
        ceiling=result.ceiling, stop_reason=result.why_stopped(),
        cost=meter.summary() if meter else "",
    )


# ----------------------------------------------------------- cover letter ----


@dataclass
class CoverAttempt:
    number: int
    letter: CoverLetter
    violations: list[ground.Violation] = field(default_factory=list)
    repair: ground.LetterRepair | None = None
    verify_report: VerifyReport | None = None
    rendered: Rendered | None = None
    review: letter_review.LetterReview | None = None

    @property
    def reads_well(self) -> bool:
        return self.review is None or self.review.ok

    @property
    def document(self) -> CoverLetter:
        return self.repair.letter if self.repair is not None else self.letter

    @property
    def grounded(self) -> bool:
        return not self.violations

    @property
    def repaired(self) -> bool:
        return self.repair is not None

    def note(self) -> str:
        if self.violations:
            return f"letter rejected by the grounding gate ({ground.summarize(self.violations)})"
        pages = self.verify_report.page_count if self.verify_report else "?"
        parses = self.verify_report.ok if self.verify_report else False
        note = f"letter {'parses' if parses else 'failed its checks'}, {pages} page(s)"
        if self.repair is not None:
            note += f", {len(self.repair.dropped)} paragraph(s) removed"
        return note


@dataclass
class CoverRun:
    attempts: list[CoverAttempt]
    best: CoverAttempt
    blocked_terms: list[str]
    cancelled: bool = False

    @property
    def ok(self) -> bool:
        return self.best.grounded and bool(self.best.verify_report and self.best.verify_report.ok)


def generate_cover(
    profile: Profile,
    jd: JobDescription,
    corpus: Corpus | None,
    cfg: Settings,
    llm_call: LLMCall,
    *,
    out_dir: Path,
    progress: Progress | None = None,
) -> CoverRun:
    """Grounding, then craft. There is still no *score* for a cover letter — inventing one
    would be inventing a metric, and the résumé's proxy is already an explicitly-labelled
    proxy — but "does this read like a form letter?" has legible answers, and
    letter_review.py checks them.

    The two questions are different and both are needed. ground.py asks whether any of it is
    false. A letter can pass that completely and still open "I am writing to express my
    interest", which is the single most common first line in the pile and the specific thing
    a reader is scanning for.
    """
    from . import cover

    index = source_index(profile, corpus)
    report = progress or Progress()
    allowed = cover.allowed_terms(jd)
    attempts: list[CoverAttempt] = []
    blocked: list[str] = []
    feedback = ""
    cancelled = False
    out_dir.mkdir(parents=True, exist_ok=True)
    total = max(1, cfg.MAX_ITER)

    for number in range(1, total + 1):
        where = {"document": "cover_letter", "attempt": number, "attempts": total}
        repair_feedback = ""
        try:
            report(TAILORING, **where)
            letter = cover.write(profile, jd, corpus, cfg, llm_call, feedback=feedback)
            attempt = CoverAttempt(number=number, letter=letter)

            report(GROUNDING, **where)
            attempt.violations = ground.check_letter(letter, profile, index, allowed_terms=allowed)
            attempts.append(attempt)
            if attempt.violations:
                blocked = list(dict.fromkeys(blocked + ground.unsupported_terms(attempt.violations)))
                salvaged = ground.repair_letter(
                    letter, profile, index, attempt.violations, allowed_terms=allowed
                )
                if not salvaged.ok:
                    feedback = ground.feedback(attempt.violations)
                    report(REJECTED, **where, reason=ground.summarize(attempt.violations))
                    continue
                attempt.repair = salvaged
                attempt.violations = []
                repair_feedback = ground.feedback(salvaged.dropped)
                report(
                    REPAIRED, **where, reason=ground.summarize(salvaged.dropped),
                    dropped=len(salvaged.dropped),
                )

            written = attempt.document

            report(RENDERING, **where)
            attempt.rendered = render_cover_letter(written, profile, out_dir, cfg)

            report(VERIFYING, **where)
            attempt.verify_report = verify_letter(
                attempt.rendered.pdf_path, written, profile,
                max_pages=cfg.COVER_LETTER_MAX_PAGES, page_count=attempt.rendered.page_count,
            )
            attempt.review = letter_review.review(written, jd, profile)
            report(
                SCORED, **where, parses=attempt.verify_report.ok,
                pages=attempt.verify_report.page_count, words=written.word_count(),
                reads_well=attempt.review.ok,
            )
        except Cancelled:
            cancelled = True
            if not attempts:
                raise
            break

        if attempt.verify_report.ok and not attempt.repaired and attempt.reads_well:
            break
        parts = [repair_feedback] if repair_feedback else []
        if not attempt.verify_report.ok:
            parts.append(
                "The rendered PDF failed its checks:\n"
                + "\n".join(f"  - {item}" for item in attempt.verify_report.missing[:10])
            )
        if attempt.review is not None:
            parts.append(letter_review.feedback(attempt.review))
        feedback = "\n\n".join(p for p in parts if p)

    best = max(
        attempts,
        key=lambda a: (
            a.grounded,
            bool(a.verify_report and a.verify_report.ok),
            a.reads_well,
            -len(a.review.failed) if a.review else 0,
            not a.repaired,
        ),
    )
    if best.grounded and best is not attempts[-1]:
        best.rendered = render_cover_letter(best.document, profile, out_dir, cfg)
        best.verify_report = verify_letter(
            best.rendered.pdf_path, best.document, profile,
            max_pages=cfg.COVER_LETTER_MAX_PAGES, page_count=best.rendered.page_count,
        )
    (out_dir / "cover_letter.json").write_text(
        json.dumps(best.document.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return CoverRun(attempts=attempts, best=best, blocked_terms=blocked, cancelled=cancelled)


# ------------------------------------------------------------------ run ----

MODES = ("resume", "cover", "both")


@dataclass
class Run:
    """One invocation of `gen`, in whichever of the three modes (PLAN.md §1)."""

    out_dir: Path
    mode: str
    report_path: Path
    resume: RunResult | None = None
    cover: CoverRun | None = None
    cancelled: bool = False
    record_path: Path | None = None
    # What the run actually cost. None when nobody was counting.
    meter: Meter | None = None

    @property
    def ok(self) -> bool:
        parts = [p for p in (self.resume, self.cover) if p is not None]
        return bool(parts) and not self.cancelled and all(p.ok for p in parts)


def run(
    profile: Profile,
    jd: JobDescription,
    corpus: Corpus | None,
    cfg: Settings,
    llm_call: LLMCall,
    *,
    out_dir: Path,
    mode: str = "both",
    progress: Progress | None = None,
    meter: Meter | None = None,
) -> Run:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    index = source_index(profile, corpus)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "report.md"
    cancelled = False

    resume_result = None
    if mode in ("resume", "both"):
        try:
            resume_result = generate(
                profile, jd, corpus, cfg, llm_call,
                out_dir=out_dir, progress=progress, write_report=False,
            )
            cancelled = resume_result.cancelled
        except Cancelled:
            # Cancelled before the first attempt produced anything. There is no partial
            # résumé to describe, but the run still gets a record saying what happened.
            cancelled = True

    cover_result = None
    if mode in ("cover", "both") and not cancelled:
        try:
            cover_result = generate_cover(
                profile, jd, corpus, cfg, llm_call, out_dir=out_dir, progress=progress
            )
            cancelled = cover_result.cancelled
        except Cancelled:
            cancelled = True

    if progress is not None:
        # Deliberately not through progress(): the report and the record still get written
        # for a cancelled run, and a checkpoint here would abort exactly that.
        progress.history.append((WRITING_REPORT, {}))
        if progress.sink:
            progress.sink(WRITING_REPORT, {})

    sections = []
    if resume_result is not None:
        sections.append(resume_report(resume_result, profile, jd, index, cfg, meter))
    if cover_result is not None:
        sections.append(report_module.cover_section(cover_result, jd, index))
    report_path.write_text("\n".join(sections), encoding="utf-8")

    result = Run(
        out_dir=out_dir, mode=mode, report_path=report_path,
        resume=resume_result, cover=cover_result, cancelled=cancelled,
    )
    result.meter = meter
    result.record_path = runrecord.save(
        build_record(result, jd, index, cfg, meter), out_dir
    )
    if progress is not None:
        stage = CANCELLED if cancelled else DONE
        progress.history.append((stage, {"ok": result.ok}))
        if progress.sink:
            progress.sink(stage, {"ok": result.ok})
    return result


def build_record(
    result: Run, jd: JobDescription, index: SourceIndex, cfg: Settings, meter: Meter | None = None
) -> runrecord.RunRecord:
    """The structured account of the run, for anything that is not a human reading prose."""
    documents: list[runrecord.DocumentRecord] = []

    if result.resume is not None:
        best = result.resume.best
        documents.append(
            runrecord.DocumentRecord(
                kind="resume",
                pdf=best.rendered.pdf_path.name if best.rendered else "",
                ok=result.resume.ok,
                iterations=len(result.resume.attempts),
                verify=runrecord.verify_record(best.verify_report),
                claims=runrecord.resume_claims(best.document, index),
                blocked_terms=list(result.resume.blocked_terms),
                violations=[str(v) for v in best.violations],
                removed=best.repair.notes() if best.repair else [],
                ats=best.review.as_dict() if best.review else [],
            )
        )
    if result.cover is not None:
        best_cover = result.cover.best
        documents.append(
            runrecord.DocumentRecord(
                kind="cover_letter",
                pdf=best_cover.rendered.pdf_path.name if best_cover.rendered else "",
                ok=result.cover.ok,
                iterations=len(result.cover.attempts),
                verify=runrecord.verify_record(best_cover.verify_report),
                claims=runrecord.cover_claims(best_cover.document, index),
                blocked_terms=list(result.cover.blocked_terms),
                violations=[str(v) for v in best_cover.violations],
                ats=best_cover.review.as_dict() if best_cover.review else [],
                removed=(
                    [f"{v.where} — {v.detail}" for v in best_cover.repair.dropped]
                    if best_cover.repair
                    else []
                ),
            )
        )

    return runrecord.RunRecord(
        run_id=result.out_dir.name,
        created_at=runrecord.now(),
        mode=result.mode,
        ok=result.ok,
        cancelled=result.cancelled,
        jd=runrecord.job_record(jd),
        settings={
            "threshold": cfg.SCORE_THRESHOLD,
            "max_iter": cfg.MAX_ITER,
            "ceiling_slack": cfg.CEILING_SLACK,
            "min_gain": cfg.MIN_GAIN,
            "resume_max_pages": cfg.RESUME_MAX_PAGES,
            "cover_letter_words": cfg.COVER_LETTER_WORDS,
            "strict_score": cfg.STRICT_SCORE,
            "model": cfg.LLM_MODEL,
        },
        usage=meter.as_dict() if meter else {},
        score=runrecord.score_record(
            result.resume.best.score if result.resume else None, cfg.SCORE_THRESHOLD,
            ceiling=result.resume.ceiling if result.resume else None,
            stop_reason=result.resume.stop_reason if result.resume else "",
            slack=cfg.CEILING_SLACK,
        ),
        documents=documents,
    )
