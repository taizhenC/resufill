"""`run.json` — what a run concluded, in a form something other than a human can read.

`report.md` is prose for a person. It is not an API, and re-deriving a score by parsing it
would make a human-readable artefact into a parsing target — the thing most likely to break
the next time a heading gets reworded. So every run also writes this.

The important decision here is that **cited source text is embedded, not referenced**.

A citation is a receipt for a claim on a document you may have already sent. If this file
stored only source *ids* and something re-read `profile.yaml` to display them, then editing
the record — which the tool actively encourages, because closing a gap means adding to it —
would silently change what a past résumé appears to have been standing on. The audit would
still render, and it would be wrong, and nothing would say so. Embedding costs a few KB per
run and makes the trail true forever.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from .document import CoverLetter, ResumeDoc
from .jd import JobDescription
from .score import Ceiling, Score
from .source import SourceIndex
from .verify import VerifyReport

FILENAME = "run.json"
# Bumped when a field changes meaning. Readers check it rather than guessing from shape.
SCHEMA_VERSION = 1


class CitedSource(BaseModel):
    id: str
    label: str
    # A snapshot of what the source said at generation time. See the module docstring.
    text: str


class Claim(BaseModel):
    """One bullet or paragraph, with everything that licensed it."""

    where: str
    text: str
    sources: list[CitedSource] = Field(default_factory=list)


class ComponentRecord(BaseModel):
    name: str
    label: str
    weight: float
    raw: float
    points: float
    detail: str


class GapRecord(BaseModel):
    keyword: str
    in_record: bool
    where: str = ""


class ScoreRecord(BaseModel):
    total: float
    threshold: float
    met: bool
    # The highest score this record could have reached for this posting, and whether the run
    # got there. Without it, `total` below `threshold` is unreadable: it could be a tailoring
    # miss or it could be the only honest answer available.
    ceiling: float | None = None
    at_ceiling: bool = False
    unreachable: list[str] = Field(default_factory=list)
    stop_reason: str = ""
    components: list[ComponentRecord] = Field(default_factory=list)
    matched: list[str] = Field(default_factory=list)
    # Split at write time rather than at read time: the two lists mean different things and
    # a consumer that has to remember to filter will eventually forget.
    gaps_absent: list[GapRecord] = Field(default_factory=list)
    gaps_unsurfaced: list[GapRecord] = Field(default_factory=list)
    stuffed: list[str] = Field(default_factory=list)
    unaddressed_qualifications: list[str] = Field(default_factory=list)


class VerifyRecord(BaseModel):
    ok: bool
    page_count: int
    missing: list[str] = Field(default_factory=list)
    checks: dict[str, bool] = Field(default_factory=dict)


class DocumentRecord(BaseModel):
    kind: str  # "resume" | "cover_letter"
    pdf: str = ""  # filename within the run directory, empty when none was written
    ok: bool = False
    iterations: int = 0
    verify: VerifyRecord | None = None
    claims: list[Claim] = Field(default_factory=list)
    blocked_terms: list[str] = Field(default_factory=list)
    violations: list[str] = Field(default_factory=list)
    # What the gate removed from the draft so the rest could be kept. The document below is
    # smaller than the model wrote, and this is the difference — recorded rather than
    # silently absorbed, because "the résumé is shorter than you expected" is a question
    # somebody will ask, and this is the answer.
    removed: list[str] = Field(default_factory=list)
    # The machine-readability rubric, check by check. See ats.py for what is in it and, more
    # importantly, what is deliberately left out.
    ats: list[dict] = Field(default_factory=list)


class JobRecord(BaseModel):
    title: str = ""
    company: str = ""
    seniority: str = ""
    min_years: int | None = None
    hard_skills: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    qualifications: list[str] = Field(default_factory=list)


class RunRecord(BaseModel):
    schema_version: int = SCHEMA_VERSION
    run_id: str
    created_at: str
    mode: str
    ok: bool = False
    cancelled: bool = False
    jd: JobRecord = Field(default_factory=JobRecord)
    settings: dict[str, float | int | bool | str] = Field(default_factory=dict)
    # What the run cost: model calls, tokens, and seconds spent waiting on the model. Empty
    # for a run made before this was counted. Deliberately not a price — see meter.py.
    usage: dict[str, float | int] = Field(default_factory=dict)
    score: ScoreRecord | None = None
    documents: list[DocumentRecord] = Field(default_factory=list)

    def document(self, kind: str) -> DocumentRecord | None:
        return next((d for d in self.documents if d.kind == kind), None)


class RunSummary(BaseModel):
    """One line in the history list. Deliberately cheap: the UI shows dozens of these."""

    run_id: str
    created_at: str = ""
    mode: str = ""
    ok: bool = False
    cancelled: bool = False
    title: str = ""
    company: str = ""
    total: float | None = None
    threshold: float | None = None
    pdfs: list[str] = Field(default_factory=list)
    # True for runs made before run.json existed. They are still listed and their PDFs are
    # still downloadable; there is simply nothing structured to show. Crashing on them, or
    # hiding them, would both be worse.
    legacy: bool = False


# ------------------------------------------------------------------ build ----


def _claims(cited: Iterable[tuple[str, object]], index: SourceIndex) -> list[Claim]:
    out: list[Claim] = []
    for where, item in cited:
        sources = [
            CitedSource(id=sid, label=index[sid].label, text=index[sid].text)
            for sid in getattr(item, "source_ids", [])
            if sid in index
        ]
        out.append(Claim(where=where, text=getattr(item, "text", ""), sources=sources))
    return out


def resume_claims(doc: ResumeDoc, index: SourceIndex) -> list[Claim]:
    return _claims(doc.bullets(), index)


def cover_claims(letter: CoverLetter, index: SourceIndex) -> list[Claim]:
    return _claims(letter.cited(), index)


def verify_record(report: VerifyReport | None) -> VerifyRecord | None:
    if report is None:
        return None
    return VerifyRecord(
        ok=report.ok, page_count=report.page_count,
        missing=list(report.missing), checks=dict(report.checks),
    )


def score_record(
    score: Score | None,
    threshold: float,
    *,
    ceiling: Ceiling | None = None,
    stop_reason: str = "",
    slack: float = 2.0,
) -> ScoreRecord | None:
    if score is None:
        return None
    return ScoreRecord(
        total=score.total,
        threshold=threshold,
        met=score.total >= threshold,
        ceiling=ceiling.total if ceiling else None,
        at_ceiling=bool(ceiling and score.total >= ceiling.total - slack),
        unreachable=list(ceiling.unreachable) if ceiling else [],
        stop_reason=stop_reason,
        components=[
            ComponentRecord(
                name=c.name, label=c.label, weight=c.weight, raw=c.raw,
                points=round(c.points, 2), detail=c.detail,
            )
            for c in score.components
        ],
        matched=list(score.matched),
        gaps_absent=[GapRecord(keyword=g.keyword, in_record=False) for g in score.real_gaps()],
        gaps_unsurfaced=[
            GapRecord(keyword=g.keyword, in_record=True, where=g.where) for g in score.unsurfaced()
        ],
        stuffed=list(score.stuffed),
        unaddressed_qualifications=list(score.unaddressed_qualifications),
    )


def job_record(jd: JobDescription) -> JobRecord:
    return JobRecord(
        title=jd.title, company=jd.company, seniority=jd.seniority, min_years=jd.min_years,
        hard_skills=list(jd.hard_skills), keywords=list(jd.keywords),
        qualifications=list(jd.qualifications),
    )


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# --------------------------------------------------------------- io / scan ----


def save(record: RunRecord, out_dir: Path) -> Path:
    path = out_dir / FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
    return path


def load(out_dir: Path) -> RunRecord | None:
    """None when the run predates this file, or when it cannot be read.

    A malformed record must not take down a history listing: it is derived data about one
    run, and every other run in the directory is still fine.
    """
    path = out_dir / FILENAME
    if not path.exists():
        return None
    try:
        return RunRecord.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _pdfs(out_dir: Path) -> list[str]:
    return sorted(p.name for p in out_dir.glob("*.pdf"))


def summarize(out_dir: Path) -> RunSummary:
    record = load(out_dir)
    if record is None:
        # Pre-W0 run, or an unreadable record. Still listable, still downloadable.
        stat = out_dir.stat()
        return RunSummary(
            run_id=out_dir.name,
            created_at=datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(timespec="seconds"),
            pdfs=_pdfs(out_dir),
            legacy=True,
        )
    return RunSummary(
        run_id=record.run_id, created_at=record.created_at, mode=record.mode,
        ok=record.ok, cancelled=record.cancelled,
        title=record.jd.title, company=record.jd.company,
        total=record.score.total if record.score else None,
        threshold=record.score.threshold if record.score else None,
        pdfs=[d.pdf for d in record.documents if d.pdf] or _pdfs(out_dir),
    )


def scan(root: Path) -> list[RunSummary]:
    """Every run directory, newest first. `out/` is the source of truth; this is just a read."""
    if not root.is_dir():
        return []
    summaries = [summarize(d) for d in root.iterdir() if d.is_dir()]
    return sorted(summaries, key=lambda s: (s.created_at, s.run_id), reverse=True)


def read_json(out_dir: Path) -> dict | None:
    """The raw record, for an API that wants to pass it straight through untouched."""
    path = out_dir / FILENAME
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
