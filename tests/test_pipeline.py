"""The loop, end to end, against a scripted model.

Every run here goes all the way to a real PDF and back, because the loop's decisions
depend on facts only the PDF has — whether it parses, how many pages it is.
"""

import json

import pytest
from conftest import needs_chromium

from resume_fill.config import Settings
from resume_fill.jd import parse_deterministic
from resume_fill.llm import LLMError
from resume_fill.pipeline import generate, run_dir

POSTING = parse_deterministic(
    "Backend Engineer, Data Platform\n\n"
    "About Northwind\n\n"
    "Basic Qualifications\n"
    "- Production Python\n"
    "- Strong PostgreSQL\n"
    "- Kubernetes in production\n"
)

HONEST = {
    "headline": "Backend engineer — data pipelines",
    "experience": [
        {
            "source_id": "exp-northwind-backend",
            "bullets": [
                {
                    "text": "Rewrote the nightly ingestion job in Python as an asyncio worker pool, "
                    "cutting the run from 51 minutes to 9.",
                    "source_ids": ["exp-northwind-backend.h1"],
                },
                {
                    "text": "Added contract tests across the 14 upstream PostgreSQL feeds, catching "
                    "3 silent schema changes.",
                    "source_ids": ["exp-northwind-backend.h2"],
                },
            ],
        }
    ],
    "projects": [
        {
            "source_id": "proj-tidepool",
            "bullets": [
                {
                    "text": "Packed 40 years of NOAA harmonic constants into a 6 MB SQLite file.",
                    "source_ids": ["proj-tidepool.h1"],
                }
            ],
        }
    ],
    "education": [
        {
            "source_id": "edu-hunter-cs",
            "bullets": [{"text": "Coursework: Databases, Operating Systems.",
                         "source_ids": ["edu-hunter-cs.h1"]}],
        }
    ],
    "skills": {"Languages": ["Python", "SQL"], "Data": ["PostgreSQL", "SQLite"]},
    "section_order": ["skills", "experience", "projects", "education"],
}

# One bad bullet in an otherwise honest draft. Removing it leaves a document that passes
# the gate, so this is the case the loop repairs rather than throws away.
FABRICATED = json.loads(json.dumps(HONEST))
FABRICATED["experience"][0]["bullets"][0]["text"] = (
    "Ran the ingestion pipeline on Kubernetes, cutting runtime 94%."
)

# Every bullet fabricated. There is nothing to salvage: cutting the unsupportable parts
# leaves an empty document, and an empty résumé is a failed run wearing a PDF.
UNSALVAGEABLE = json.loads(json.dumps(HONEST))
for _entry in (
    *UNSALVAGEABLE["experience"], *UNSALVAGEABLE["projects"], *UNSALVAGEABLE["education"]
):
    for _bullet in _entry["bullets"]:
        _bullet["text"] = "Ran production Kubernetes clusters, cutting runtime 94%."


# The honest draft ceilings at 71.2 against this posting, because it asks for Kubernetes
# and nothing in the record has ever touched it. Loop-control tests therefore use a
# threshold below that ceiling; the ceiling itself is asserted in its own test.
HONEST_CEILING = 71.2


def _cfg(tmp_path, **kwargs) -> Settings:
    return Settings(**{"OUT_DIR": tmp_path / "out", "MAX_ITER": 3, "SCORE_THRESHOLD": 70, **kwargs})


def _scripted(*responses):
    """A model that returns each response in turn, repeating the last one forever."""
    calls = []

    def call(system, user):
        calls.append(user)
        return responses[min(len(calls) - 1, len(responses) - 1)]

    call.prompts = calls
    return call


@needs_chromium
def test_a_truthful_first_draft_runs_straight_through(example_profile, tmp_path):
    cfg = _cfg(tmp_path)
    llm = _scripted(HONEST)
    result = generate(example_profile, POSTING, None, cfg, llm, out_dir=tmp_path / "run")

    assert result.ok
    assert len(result.attempts) == 1
    assert result.best.verify_report.ok
    assert (tmp_path / "run" / "resume.pdf").exists()
    assert (tmp_path / "run" / "report.md").exists()
    assert (tmp_path / "run" / "resume.json").exists()


@needs_chromium
def test_one_fabricated_bullet_costs_the_bullet_not_the_draft(example_profile, tmp_path):
    """The loop's whole reason for existing, and the thing that used to make it expensive:
    the first draft claims Kubernetes and a 94% improvement, neither of which is in the
    record. That is one bad bullet out of four, and it used to cost the other three plus a
    whole iteration."""
    cfg = _cfg(tmp_path, SCORE_THRESHOLD=99, MAX_ITER=2)
    llm = _scripted(FABRICATED, HONEST)
    result = generate(example_profile, POSTING, None, cfg, llm, out_dir=tmp_path / "run")

    first = result.attempts[0]
    assert first.repaired
    assert first.grounded  # of the rendered document: it went back through check()
    assert first.rendered is not None and first.score is not None
    assert {v.kind for v in first.repair.dropped} == {"unsupported_term", "unsupported_number"}
    assert [b.text for _, b in first.document.bullets()] != [b.text for _, b in first.doc.bullets()]

    retry_prompt = llm.prompts[1]
    assert "WHY THE LAST ATTEMPT WAS REJECTED" in retry_prompt
    assert "Kubernetes" in retry_prompt and "94%" in retry_prompt

    assert result.ok
    assert "Kubernetes" in result.blocked_terms


@needs_chromium
def test_the_repaired_draft_is_kept_when_nothing_better_arrives(example_profile, tmp_path):
    """One iteration, one flawed draft, and a PDF at the end of it. Before repair this run
    produced nothing at all."""
    cfg = _cfg(tmp_path, MAX_ITER=1)
    result = generate(example_profile, POSTING, None, cfg, _scripted(FABRICATED),
                      out_dir=tmp_path / "run")

    assert result.ok
    assert result.best.repaired
    assert (tmp_path / "run" / "resume.pdf").exists()
    saved = json.loads((tmp_path / "run" / "resume.json").read_text(encoding="utf-8"))
    # resume.json is the rendered document, not the drafted one, or a diff of two runs
    # compares fiction.
    assert "Kubernetes" not in json.dumps(saved)


@needs_chromium
def test_an_untouched_draft_wins_a_tie_against_a_repaired_one(example_profile, tmp_path):
    """A repaired document is the same document with something cut out of it, so at equal
    score the one that needed no cutting is the better artefact."""
    cfg = _cfg(tmp_path, SCORE_THRESHOLD=99, MAX_ITER=2)
    result = generate(example_profile, POSTING, None, cfg, _scripted(FABRICATED, HONEST),
                      out_dir=tmp_path / "run")

    assert result.best is result.attempts[1]
    assert not result.best.repaired


@needs_chromium
def test_a_draft_that_never_grounds_writes_no_pdf(example_profile, tmp_path):
    """PLAN.md decision 5 is a hard block, not a warning printed at the end. Repair does not
    soften it: a draft with nothing supportable left in it is still a rejection."""
    cfg = _cfg(tmp_path, MAX_ITER=2)
    result = generate(example_profile, POSTING, None, cfg, _scripted(UNSALVAGEABLE),
                      out_dir=tmp_path / "run")

    assert not result.ok
    assert result.best.violations
    assert not (tmp_path / "run" / "resume.pdf").exists()
    # The report is still written: it is how you find out what was blocked and why.
    assert "Unresolved grounding violations" in (tmp_path / "run" / "report.md").read_text(encoding="utf-8")


@needs_chromium
def test_a_rejected_draft_is_never_rendered(example_profile, tmp_path):
    """Launching Chromium for claims that are about to be rejected wastes a second an
    iteration and leaves an artefact nobody should look at."""
    cfg = _cfg(tmp_path, MAX_ITER=1)
    result = generate(example_profile, POSTING, None, cfg, _scripted(UNSALVAGEABLE),
                      out_dir=tmp_path / "run")
    assert result.attempts[0].rendered is None
    assert result.attempts[0].verify_report is None


@needs_chromium
def test_the_best_attempt_is_kept_not_the_last(example_profile, tmp_path):
    """Iteration N can score worse than N-1 — the feedback pushes on gaps and pushing can
    cost coverage elsewhere. Shipping the final draft regardless would make more
    iterations actively harmful."""
    weaker = json.loads(json.dumps(HONEST))
    weaker["experience"][0]["bullets"] = weaker["experience"][0]["bullets"][:1]
    weaker["projects"] = []
    weaker["skills"] = {"Languages": ["Python"]}

    cfg = _cfg(tmp_path, SCORE_THRESHOLD=100, MAX_ITER=2)  # unreachable: force both attempts
    result = generate(example_profile, POSTING, None, cfg, _scripted(HONEST, weaker),
                      out_dir=tmp_path / "run")

    assert len(result.attempts) == 2
    assert result.best is result.attempts[0]
    assert result.best.total > result.attempts[1].total
    # The PDF on disk has to be the one the report describes.
    text = (tmp_path / "run" / "resume.pdf").read_bytes()
    assert text[:4] == b"%PDF"
    saved = json.loads((tmp_path / "run" / "resume.json").read_text(encoding="utf-8"))
    assert len(saved["experience"][0]["bullets"]) == 2


@needs_chromium
def test_the_loop_stops_as_soon_as_the_threshold_is_met(example_profile, tmp_path):
    cfg = _cfg(tmp_path, SCORE_THRESHOLD=1, MAX_ITER=4)
    result = generate(example_profile, POSTING, None, cfg, _scripted(HONEST), out_dir=tmp_path / "run")
    assert len(result.attempts) == 1
    assert result.met_threshold


@needs_chromium
def test_an_honest_ceiling_below_the_threshold_still_produces_a_pdf(example_profile, tmp_path):
    """PLAN.md open question 5: a low score the gate refused to inflate is information, not
    a build failure. The posting wants Kubernetes and the record has never seen it."""
    cfg = _cfg(tmp_path, SCORE_THRESHOLD=99, MAX_ITER=2)
    result = generate(example_profile, POSTING, None, cfg, _scripted(HONEST), out_dir=tmp_path / "run")

    assert result.ok
    assert not result.met_threshold
    # Two of three named technologies, two of three qualifications. The missing third is
    # Kubernetes, and the loop had no honest way to reach it.
    assert result.best.total == HONEST_CEILING
    assert result.best.score.component("hard_skills").detail == "2 of 3 named technologies appear"

    report = (tmp_path / "run" / "report.md").read_text(encoding="utf-8")
    assert "Not in your record at all" in report
    assert "Kubernetes" in report
    assert "local proxy" in report  # the number is never presented bare


# ------------------------------------------------- run.json, stages, cancel ----


@needs_chromium
def test_a_run_writes_a_structured_record_beside_the_report(example_profile, tmp_path):
    """report.md is prose for a person. Re-deriving a score by parsing it would make a
    human-readable artefact into a parsing target."""
    from resume_fill import runrecord
    from resume_fill.pipeline import run

    out = tmp_path / "run"
    result = run(example_profile, POSTING, None, _cfg(tmp_path), _scripted(HONEST),
                 out_dir=out, mode="resume")

    assert result.record_path == out / "run.json"
    record = runrecord.load(out)
    assert record.mode == "resume"
    assert record.ok is True
    assert record.cancelled is False
    assert record.jd.company == "Northwind"
    assert record.score.total == HONEST_CEILING
    assert record.settings["model"]

    doc = record.document("resume")
    assert doc.pdf == "resume.pdf"
    assert doc.iterations >= 1
    assert doc.verify.ok is True
    # Every bullet carries its source text, not just the id.
    assert doc.claims and all(c.sources for c in doc.claims)
    assert "asyncio worker pool" in doc.claims[0].sources[0].text


# Defined here rather than imported from test_cover, which already imports POSTING from
# this module — the other direction would be a cycle.
LETTER = {
    "addressee": "Hiring Manager",
    "paragraphs": [
        {
            "text": "I rewrote a nightly ingestion job as an asyncio worker pool and cut the run "
            "from 51 minutes to 9.",
            "source_ids": ["exp-northwind-backend.h1"],
        }
    ],
}


@needs_chromium
def test_both_documents_appear_in_one_record(example_profile, tmp_path):
    from resume_fill import runrecord
    from resume_fill.pipeline import run

    out = tmp_path / "run"

    def call(system, user):
        return LETTER if "Write a cover letter" in user else HONEST

    run(example_profile, POSTING, None, _cfg(tmp_path), call, out_dir=out, mode="both")
    record = runrecord.load(out)
    assert [d.kind for d in record.documents] == ["resume", "cover_letter"]
    assert record.document("cover_letter").claims
    assert record.document("cover_letter").pdf == "cover_letter.pdf"


@needs_chromium
def test_stages_are_reported_in_order(example_profile, tmp_path):
    """The CLI used to print one line per attempt, which meant up to a minute of silence
    between them. These are the moments the pipeline is between two blocking calls."""
    from resume_fill.pipeline import run
    from resume_fill.progress import Progress

    seen: list[str] = []
    progress = Progress(sink=lambda stage, detail: seen.append(stage))
    run(example_profile, POSTING, None, _cfg(tmp_path, SCORE_THRESHOLD=1), _scripted(HONEST),
        out_dir=tmp_path / "run", mode="resume", progress=progress)

    assert seen[:6] == ["tailoring", "grounding", "rendering", "verifying", "scoring", "scored"]
    assert seen[-2:] == ["writing_report", "done"]


@needs_chromium
def test_a_rejected_attempt_reports_why_and_skips_rendering(example_profile, tmp_path):
    from resume_fill.pipeline import run
    from resume_fill.progress import Progress

    events: list[tuple[str, dict]] = []
    progress = Progress(sink=lambda stage, detail: events.append((stage, detail)))
    run(example_profile, POSTING, None, _cfg(tmp_path, MAX_ITER=1), _scripted(UNSALVAGEABLE),
        out_dir=tmp_path / "run", mode="resume", progress=progress)

    stages = [s for s, _ in events]
    assert "rejected" in stages
    assert "rendering" not in stages  # never render claims that are about to be rejected
    reason = next(d["reason"] for s, d in events if s == "rejected")
    assert "unsupported_term" in reason


@needs_chromium
def test_a_repaired_attempt_says_so_and_still_renders(example_profile, tmp_path):
    from resume_fill.pipeline import run
    from resume_fill.progress import Progress

    events: list[tuple[str, dict]] = []
    progress = Progress(sink=lambda stage, detail: events.append((stage, detail)))
    run(example_profile, POSTING, None, _cfg(tmp_path, MAX_ITER=1), _scripted(FABRICATED),
        out_dir=tmp_path / "run", mode="resume", progress=progress)

    stages = [s for s, _ in events]
    assert "repaired" in stages
    assert "rejected" not in stages
    assert "rendering" in stages
    detail = next(d for s, d in events if s == "repaired")
    assert detail["dropped"] == 2


@needs_chromium
def test_cancelling_between_stages_stops_the_run_and_keeps_what_finished(example_profile, tmp_path):
    """Cooperative on purpose: killing the thread mid-render would leave a half-written PDF
    that nothing can tell is corrupt."""
    import threading

    from resume_fill import runrecord
    from resume_fill.pipeline import run
    from resume_fill.progress import Progress

    event = threading.Event()
    # Let the first attempt complete, then ask to stop before the second one starts.
    def sink(stage: str, detail: dict) -> None:
        if stage == "scored":
            event.set()

    out = tmp_path / "run"
    result = run(
        example_profile, POSTING, None, _cfg(tmp_path, SCORE_THRESHOLD=99, MAX_ITER=4),
        _scripted(HONEST), out_dir=out, mode="resume",
        progress=Progress(sink=sink, cancel=event),
    )

    assert result.cancelled is True
    assert result.ok is False
    assert len(result.resume.attempts) == 1  # stopped instead of using all four
    # The report and the record are still written; the run happened, it just stopped early.
    assert (out / "report.md").exists()
    record = runrecord.load(out)
    assert record.cancelled is True
    assert record.document("resume").pdf == "resume.pdf"


@needs_chromium
def test_cancelling_before_anything_finishes_still_records_the_run(example_profile, tmp_path):
    import threading

    from resume_fill import runrecord
    from resume_fill.pipeline import run
    from resume_fill.progress import Progress

    event = threading.Event()
    event.set()  # cancelled before the first stage even reports

    out = tmp_path / "run"
    result = run(example_profile, POSTING, None, _cfg(tmp_path), _scripted(HONEST),
                 out_dir=out, mode="resume", progress=Progress(cancel=event))

    assert result.cancelled is True
    assert result.resume is None
    assert not (out / "resume.pdf").exists()
    record = runrecord.load(out)
    assert record.cancelled is True and record.documents == []


def test_the_run_directory_names_the_company_the_role_and_the_date(tmp_path):
    from datetime import date

    cfg = Settings(OUT_DIR=tmp_path / "out")
    path = run_dir(POSTING, cfg, today=date(2026, 7, 26))
    assert path.name == "northwind-backend-engineer-data-platform-2026-07-26"


def test_an_unrelated_json_object_does_not_become_an_empty_resume(example_profile, tmp_path):
    """Every field on ResumeDoc has a default, so `{"nope": true}` validates cleanly into a
    document with nothing in it — and grounding passes it, because there is nothing in it
    to be wrong. It has to fail here instead."""
    with pytest.raises(LLMError, match="no entries selected"):
        generate(example_profile, POSTING, None, _cfg(tmp_path), _scripted({"nope": True}),
                 out_dir=tmp_path / "run")


@needs_chromium
def test_what_repair_removed_is_written_down_not_absorbed(example_profile, tmp_path):
    """A résumé shorter than the model wrote is a question somebody will ask. Both the
    prose report and the structured record answer it."""
    from resume_fill import runrecord
    from resume_fill.pipeline import run

    out = tmp_path / "run"
    run(example_profile, POSTING, None, _cfg(tmp_path, MAX_ITER=1), _scripted(FABRICATED),
        out_dir=out, mode="resume")

    report = (out / "report.md").read_text(encoding="utf-8")
    assert "Removed so the rest could be kept" in report
    assert "Kubernetes" in report

    removed = runrecord.load(out).document("resume").removed
    assert len(removed) == 2
    assert any("Kubernetes" in item for item in removed)
