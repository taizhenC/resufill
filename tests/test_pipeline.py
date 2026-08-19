"""The loop, end to end, against a scripted model.

Every run here goes all the way to a real PDF and back, because the loop's decisions
depend on facts only the PDF has — whether it parses, how many pages it is.
"""

import json

import pytest
from conftest import needs_chromium

from resume_fill.config import Settings
from resume_fill.document import ResumeDoc
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


# Two drafts that leave something on the table on purpose. The honest one sits *at* the
# record's ceiling, so the loop now stops on it immediately — which is correct, and useless
# for testing anything about iteration. These two mention progressively fewer of the things
# the record can actually support, so there is somewhere left to go.
MIDDLING = json.loads(json.dumps(HONEST))
MIDDLING["experience"][0]["bullets"][1]["text"] = (
    "Added contract tests across the 14 upstream feeds, catching 3 silent schema changes."
)
MIDDLING["projects"] = []
MIDDLING["skills"] = {"Languages": ["Python"]}

WEAKER = json.loads(json.dumps(MIDDLING))
WEAKER["experience"][0]["bullets"] = WEAKER["experience"][0]["bullets"][:1]
WEAKER["experience"][0]["bullets"][0]["text"] = (
    "Rewrote the nightly ingestion job as an asyncio worker pool, cutting the run from 51 "
    "minutes to 9."
)
WEAKER["skills"] = {}

# The same draft with the posting's own words in the headline. Nothing else changes, and
# nothing here is a claim — the gate polices technologies and figures, not which ordinary
# words describe the same job — so those points are simply free, and the ceiling knows it.
HONEST_TITLED = json.loads(json.dumps(HONEST))
HONEST_TITLED["headline"] = "Backend engineer, data platform — Python, PostgreSQL"

# What this record can reach against this posting: 75.0. It stops short of 100 because the
# posting asks for Kubernetes and nothing in the record has ever touched it. Both numbers
# are derived rather than measured by hand — score.ceiling() computes the first from the
# record before any model call.
RECORD_CEILING = 75.0
# What the honest draft actually gets. Below the ceiling by exactly the headline: it names
# the role in its own words rather than the posting's, which is the cheapest 3.8 points on
# the page and the one thing a rewrite always can close.
HONEST_SCORE = 71.2
MIDDLING_SCORE = 46.2


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
    cfg = _cfg(tmp_path, SCORE_THRESHOLD=100, MAX_ITER=2)
    result = generate(example_profile, POSTING, None, cfg, _scripted(MIDDLING, WEAKER),
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
def test_the_loop_stops_at_what_the_record_can_reach(example_profile, tmp_path):
    """The complaint this exists to answer: a threshold of 99 against a record that tops out
    at 75.0 used to cost four model calls to learn what the first one already knew.

    ground.py is what makes stopping here honest rather than lazy — the missing points are
    Kubernetes, the record has never touched it, and no rewrite is permitted to invent it.
    """
    cfg = _cfg(tmp_path, SCORE_THRESHOLD=99, MAX_ITER=4)
    result = generate(example_profile, POSTING, None, cfg, _scripted(HONEST_TITLED),
                      out_dir=tmp_path / "run")

    assert len(result.attempts) == 1
    assert result.stop_reason == "ceiling"
    assert result.at_ceiling
    assert not result.threshold_reachable
    assert result.reachable == RECORD_CEILING
    assert result.ceiling.unreachable == ["Kubernetes"]


@needs_chromium
def test_a_draft_can_never_score_above_the_ceiling(example_profile, tmp_path):
    """The only interesting answer is False, and it used to be False.

    The ceiling conflated two halves of title_fit that have different maxima: the level a
    record shows is fixed, but the *words* a headline uses are phrasing, and phrasing the
    headline in the posting's own words is free. Measuring both against the held titles
    produced a "ceiling" a real draft scored 3.8 points above — which reads as a bug in the
    report and undermines the one thing the number is for.
    """
    from resume_fill.score import ceiling, score

    index = example_profile.sources()
    limit = ceiling(example_profile, POSTING, index)
    for draft in (HONEST, HONEST_TITLED, MIDDLING, WEAKER):
        total = score(ResumeDoc.model_validate(draft), example_profile, POSTING, index).total
        assert limit.covers(total), f"{total} > {limit.total}"


@needs_chromium
def test_the_loop_stops_when_a_rewrite_stops_buying_anything(example_profile, tmp_path):
    """Two attempts that score the same is the loop's own evidence that a third will too.
    The feedback pushes on gaps; past a point pushing only trades one keyword for another."""
    cfg = _cfg(tmp_path, SCORE_THRESHOLD=99, MAX_ITER=4)
    result = generate(example_profile, POSTING, None, cfg, _scripted(MIDDLING),
                      out_dir=tmp_path / "run")

    assert len(result.attempts) == 2
    assert result.stop_reason == "plateau"
    assert not result.at_ceiling  # it stopped short of the ceiling, and says so


@needs_chromium
def test_reaching_the_threshold_still_wins_over_everything_else(example_profile, tmp_path):
    cfg = _cfg(tmp_path, SCORE_THRESHOLD=1, MAX_ITER=4)
    result = generate(example_profile, POSTING, None, cfg, _scripted(HONEST), out_dir=tmp_path / "run")
    assert result.stop_reason == "threshold"


@needs_chromium
def test_the_ceiling_is_known_before_the_first_model_call(example_profile, tmp_path):
    """It depends only on the record and the posting, which is what makes it a stopping rule
    rather than an observation about how the run happened to go."""
    from resume_fill.score import ceiling

    limit = ceiling(example_profile, POSTING, example_profile.sources())
    assert limit.total == RECORD_CEILING
    assert limit.unreachable == ["Kubernetes"]
    assert not limit.is_reachable(80)
    assert limit.gap_to(80) == pytest.approx(5.0)


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
    assert result.best.total == HONEST_SCORE
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
    assert record.score.total == HONEST_SCORE
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
        # MIDDLING rather than HONEST: an attempt sitting at the record's ceiling now ends
        # the loop by itself, and there would be nothing left to cancel.
        _scripted(MIDDLING), out_dir=out, mode="resume",
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
