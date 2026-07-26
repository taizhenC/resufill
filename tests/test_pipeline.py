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

FABRICATED = json.loads(json.dumps(HONEST))
FABRICATED["experience"][0]["bullets"][0]["text"] = (
    "Ran the ingestion pipeline on Kubernetes, cutting runtime 94%."
)


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
def test_a_fabricated_draft_is_rejected_and_the_reason_is_fed_back(example_profile, tmp_path):
    """The loop's whole reason for existing: the first draft claims Kubernetes and a 94%
    improvement, neither of which is in the record."""
    cfg = _cfg(tmp_path)
    llm = _scripted(FABRICATED, HONEST)
    result = generate(example_profile, POSTING, None, cfg, llm, out_dir=tmp_path / "run")

    assert len(result.attempts) == 2
    assert not result.attempts[0].grounded
    assert {v.kind for v in result.attempts[0].violations} == {"unsupported_term", "unsupported_number"}

    retry_prompt = llm.prompts[1]
    assert "WHY THE LAST ATTEMPT WAS REJECTED" in retry_prompt
    assert "Kubernetes" in retry_prompt and "94%" in retry_prompt

    assert result.ok
    assert "Kubernetes" in result.blocked_terms


@needs_chromium
def test_a_draft_that_never_grounds_writes_no_pdf(example_profile, tmp_path):
    """PLAN.md decision 5 is a hard block, not a warning printed at the end."""
    cfg = _cfg(tmp_path, MAX_ITER=2)
    result = generate(example_profile, POSTING, None, cfg, _scripted(FABRICATED),
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
    result = generate(example_profile, POSTING, None, cfg, _scripted(FABRICATED),
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
