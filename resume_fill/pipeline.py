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

from . import ground
from . import report as report_module
from . import score as score_module
from .config import Settings
from .document import ResumeDoc
from .evidence import Corpus
from .jd import JobDescription
from .llm import LLMCall
from .profile import Profile
from .render import Rendered, render_resume
from .score import Score
from .verify import VerifyReport, verify


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


def generate(
    profile: Profile,
    jd: JobDescription,
    corpus: Corpus | None,
    cfg: Settings,
    llm_call: LLMCall,
    *,
    out_dir: Path,
    on_progress=None,
) -> RunResult:
    from .tailor import tailor

    index = profile.sources()
    if corpus:
        index.update(corpus.sources())

    attempts: list[Attempt] = []
    blocked: list[str] = []
    feedback = ""
    out_dir.mkdir(parents=True, exist_ok=True)

    for number in range(1, max(1, cfg.MAX_ITER) + 1):
        doc = tailor(
            profile, jd, corpus, llm_call, max_pages=cfg.RESUME_MAX_PAGES, feedback=feedback
        )
        attempt = Attempt(number=number, doc=doc)
        attempt.violations = ground.check(doc, profile, index)
        attempts.append(attempt)

        if attempt.violations:
            blocked = list(dict.fromkeys(blocked + ground.unsupported_terms(attempt.violations)))
            feedback = ground.feedback(attempt.violations)
            if on_progress:
                on_progress(attempt)
            continue

        attempt.rendered = render_resume(doc, profile, out_dir, cfg)
        attempt.verify_report = verify(
            attempt.rendered.pdf_path, doc, profile,
            max_pages=cfg.RESUME_MAX_PAGES, page_count=attempt.rendered.page_count,
        )
        attempt.score = score_module.score(doc, profile, jd, index, attempt.verify_report)
        if on_progress:
            on_progress(attempt)

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
    report_path = out_dir / "report.md"
    report_path.write_text(
        report_module.build(
            doc=best.doc, profile=profile, jd=jd, index=index,
            score=best.score or score_module.score(best.doc, profile, jd, index),
            verify_report=best.verify_report, iterations=len(attempts),
            threshold=cfg.SCORE_THRESHOLD, blocked_terms=blocked, violations=best.violations,
        ),
        encoding="utf-8",
    )
    return RunResult(
        out_dir=out_dir, attempts=attempts, best=best, report_path=report_path,
        blocked_terms=blocked, threshold=cfg.SCORE_THRESHOLD,
    )
