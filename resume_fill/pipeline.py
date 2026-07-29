"""The generate loop: tailor -> ground -> render -> verify -> score, retrying with the
reasons attached.

    profile.yaml ─┐
                  ├─→ tailor ─→ ground ─→ score ─→ render ─→ verify ─→ out/
    evidence.json ┤                 ↑        │        │
                  │                 └────────┴────────┘
    job_desc.txt ─┘        retry with violations + gaps

Two rules make the loop worth having rather than just expensive:

  1. A draft that fails grounding never gets rendered. Launching Chromium to produce a PDF
     of claims that are about to be rejected wastes a second per iteration and produces an
     artefact nobody should look at.

  2. The best attempt is kept, not the last one. Iteration 4 can score worse than
     iteration 2 — the feedback pushes on gaps, and pushing can cost coverage elsewhere —
     and silently shipping the final draft would make more iterations actively harmful.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import ground, runrecord
from . import report as report_module
from . import score as score_module
from .config import Settings
from .document import CoverLetter, ResumeDoc
from .evidence import Corpus
from .jd import JobDescription
from .llm import LLMCall
from .profile import Profile
from .progress import (
    CANCELLED,
    DONE,
    GROUNDING,
    REJECTED,
    RENDERING,
    SCORED,
    SCORING,
    TAILORING,
    VERIFYING,
    WRITING_REPORT,
    Cancelled,
    Progress,
)
from .render import Rendered, render_cover_letter, render_resume
from .score import Score
from .source import SourceIndex
from .verify import VerifyReport, verify, verify_letter


@dataclass
class Attempt:
    number: int
    doc: ResumeDoc
    violations: list[ground.Violation] = field(default_factory=list)
    score: Score | None = None
    verify_report: VerifyReport | None = None
    rendered: Rendered | None = None

    @property
    def grounded(self) -> bool:
        return not self.violations

    @property
    def total(self) -> float:
        return self.score.total if self.score else -1.0

    def rank(self) -> tuple:
        """Grounded beats ungrounded; parsing beats not parsing; then the score."""
        return (
            self.grounded,
            bool(self.verify_report and self.verify_report.ok),
            self.total,
        )

    def note(self) -> str:
        if self.violations:
            return f"rejected by the grounding gate ({ground.summarize(self.violations)})"
        parts = [f"score {self.total:.1f}"]
        if self.verify_report:
            parts.append("PDF parses" if self.verify_report.ok else "PDF failed its checks")
            parts.append(f"{self.verify_report.page_count} page(s)")
        return ", ".join(parts)


@dataclass
class RunResult:
    out_dir: Path
    attempts: list[Attempt]
    best: Attempt
    report_path: Path
    blocked_terms: list[str]
    threshold: float
    cancelled: bool = False

    @property
    def ok(self) -> bool:
        """Grounded and parses. The score not clearing the threshold is not a failure —
        it is the honest answer (PLAN.md open question 5)."""
        return self.best.grounded and bool(self.best.verify_report and self.best.verify_report.ok)

    @property
    def met_threshold(self) -> bool:
        return self.best.total >= self.threshold


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

    for number in range(1, total + 1):
        where = {"document": "resume", "attempt": number, "attempts": total}
        try:
            report(TAILORING, **where)
            doc = tailor(
                profile, jd, corpus, llm_call, max_pages=cfg.RESUME_MAX_PAGES, feedback=feedback
            )
            attempt = Attempt(number=number, doc=doc)

            report(GROUNDING, **where)
            attempt.violations = ground.check(doc, profile, index)
            attempts.append(attempt)

            if attempt.violations:
                blocked = list(dict.fromkeys(blocked + ground.unsupported_terms(attempt.violations)))
                feedback = ground.feedback(attempt.violations)
                report(REJECTED, **where, reason=ground.summarize(attempt.violations))
                continue

            report(RENDERING, **where)
            attempt.rendered = render_resume(doc, profile, out_dir, cfg)

            report(VERIFYING, **where)
            attempt.verify_report = verify(
                attempt.rendered.pdf_path, doc, profile,
                max_pages=cfg.RESUME_MAX_PAGES, page_count=attempt.rendered.page_count,
            )

            report(SCORING, **where)
            attempt.score = score_module.score(doc, profile, jd, index, attempt.verify_report)
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

        if attempt.verify_report.ok and attempt.score.total >= cfg.SCORE_THRESHOLD:
            break
        feedback = score_module.feedback(attempt.score, cfg.SCORE_THRESHOLD, attempt.verify_report)

    best = max(attempts, key=lambda a: a.rank())

    # The last attempt rendered is the one sitting on disk. If it was not the best one,
    # render the best again so the PDF matches the report that describes it.
    if best.grounded and best is not attempts[-1]:
        best.rendered = render_resume(best.doc, profile, out_dir, cfg)
        best.verify_report = verify(
            best.rendered.pdf_path, best.doc, profile,
            max_pages=cfg.RESUME_MAX_PAGES, page_count=best.rendered.page_count,
        )

    (out_dir / "resume.json").write_text(
        json.dumps(best.doc.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    result = RunResult(
        out_dir=out_dir, attempts=attempts, best=best, report_path=out_dir / "report.md",
        blocked_terms=blocked, threshold=cfg.SCORE_THRESHOLD, cancelled=cancelled,
    )
    if write_report:
        # `run()` writes a combined report when a cover letter is in play, so it asks for
        # this to be skipped rather than having it written twice.
        result.report_path.write_text(
            resume_report(result, profile, jd, index, cfg), encoding="utf-8"
        )
    return result


def resume_report(
    result: RunResult, profile: Profile, jd: JobDescription, index: SourceIndex, cfg: Settings
) -> str:
    best = result.best
    return report_module.build(
        doc=best.doc, profile=profile, jd=jd, index=index,
        score=best.score or score_module.score(best.doc, profile, jd, index),
        verify_report=best.verify_report, iterations=len(result.attempts),
        threshold=cfg.SCORE_THRESHOLD, blocked_terms=result.blocked_terms,
        violations=best.violations,
    )


# ----------------------------------------------------------- cover letter ----


@dataclass
class CoverAttempt:
    number: int
    letter: CoverLetter
    violations: list[ground.Violation] = field(default_factory=list)
    verify_report: VerifyReport | None = None
    rendered: Rendered | None = None

    @property
    def grounded(self) -> bool:
        return not self.violations

    def note(self) -> str:
        if self.violations:
            return f"letter rejected by the grounding gate ({ground.summarize(self.violations)})"
        pages = self.verify_report.page_count if self.verify_report else "?"
        parses = self.verify_report.ok if self.verify_report else False
        return f"letter {'parses' if parses else 'failed its checks'}, {pages} page(s)"


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
    """Grounding-only loop. There is no score for a cover letter and inventing one would
    be inventing a metric — the résumé's proxy is already an explicitly-labelled proxy."""
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
        try:
            report(TAILORING, **where)
            letter = cover.write(profile, jd, corpus, cfg, llm_call, feedback=feedback)
            attempt = CoverAttempt(number=number, letter=letter)

            report(GROUNDING, **where)
            attempt.violations = ground.check_letter(letter, profile, index, allowed_terms=allowed)
            attempts.append(attempt)
            if attempt.violations:
                blocked = list(dict.fromkeys(blocked + ground.unsupported_terms(attempt.violations)))
                feedback = ground.feedback(attempt.violations)
                report(REJECTED, **where, reason=ground.summarize(attempt.violations))
                continue

            report(RENDERING, **where)
            attempt.rendered = render_cover_letter(letter, profile, out_dir, cfg)

            report(VERIFYING, **where)
            attempt.verify_report = verify_letter(
                attempt.rendered.pdf_path, letter, profile,
                max_pages=cfg.COVER_LETTER_MAX_PAGES, page_count=attempt.rendered.page_count,
            )
            report(
                SCORED, **where, parses=attempt.verify_report.ok,
                pages=attempt.verify_report.page_count, words=letter.word_count(),
            )
        except Cancelled:
            cancelled = True
            if not attempts:
                raise
            break

        if attempt.verify_report.ok:
            break
        feedback = "The rendered PDF failed its checks:\n" + "\n".join(
            f"  - {item}" for item in attempt.verify_report.missing[:10]
        )

    best = max(attempts, key=lambda a: (a.grounded, bool(a.verify_report and a.verify_report.ok)))
    if best.grounded and best is not attempts[-1]:
        best.rendered = render_cover_letter(best.letter, profile, out_dir, cfg)
        best.verify_report = verify_letter(
            best.rendered.pdf_path, best.letter, profile,
            max_pages=cfg.COVER_LETTER_MAX_PAGES, page_count=best.rendered.page_count,
        )
    (out_dir / "cover_letter.json").write_text(
        json.dumps(best.letter.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8"
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
        sections.append(resume_report(resume_result, profile, jd, index, cfg))
    if cover_result is not None:
        sections.append(report_module.cover_section(cover_result, jd, index))
    report_path.write_text("\n".join(sections), encoding="utf-8")

    result = Run(
        out_dir=out_dir, mode=mode, report_path=report_path,
        resume=resume_result, cover=cover_result, cancelled=cancelled,
    )
    result.record_path = runrecord.save(
        build_record(result, jd, index, cfg), out_dir
    )
    if progress is not None:
        stage = CANCELLED if cancelled else DONE
        progress.history.append((stage, {"ok": result.ok}))
        if progress.sink:
            progress.sink(stage, {"ok": result.ok})
    return result


def build_record(
    result: Run, jd: JobDescription, index: SourceIndex, cfg: Settings
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
                claims=runrecord.resume_claims(best.doc, index),
                blocked_terms=list(result.resume.blocked_terms),
                violations=[str(v) for v in best.violations],
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
                claims=runrecord.cover_claims(best_cover.letter, index),
                blocked_terms=list(result.cover.blocked_terms),
                violations=[str(v) for v in best_cover.violations],
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
            "resume_max_pages": cfg.RESUME_MAX_PAGES,
            "cover_letter_words": cfg.COVER_LETTER_WORDS,
            "strict_score": cfg.STRICT_SCORE,
            "model": cfg.LLM_MODEL,
        },
        score=runrecord.score_record(
            result.resume.best.score if result.resume else None, cfg.SCORE_THRESHOLD
        ),
        documents=documents,
    )
