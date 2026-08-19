"""The cover letter, through the same gate as the résumé."""

import pytest
from conftest import needs_chromium
from test_pipeline import POSTING

from resume_fill.config import Settings
from resume_fill.cover import addressee_for, allowed_terms, build_prompt, paragraph_budget, write
from resume_fill.document import CoverLetter, Paragraph
from resume_fill.ground import check_letter
from resume_fill.jd import JobDescription
from resume_fill.llm import LLMError
from resume_fill.render import render_cover_letter
from resume_fill.verify import verify_letter

CFG = Settings()

LETTER = {
    "addressee": "Hiring Manager",
    "paragraphs": [
        {
            "text": "I rewrote a nightly ingestion job as an asyncio worker pool and cut the run "
            "from 51 minutes to 9, which is the shape of the problem your data platform team "
            "describes.",
            "source_ids": ["exp-northwind-backend.h1"],
        },
        {
            "text": "I also put contract tests around the 14 upstream feeds, which caught 3 silent "
            "schema changes in the first month.",
            "source_ids": ["exp-northwind-backend.h2"],
        },
        {
            "text": "Outside work I maintain tidepool, which packs 40 years of NOAA harmonic "
            "constants into a 6 MB SQLite file so lookups work offline.",
            "source_ids": ["proj-tidepool.h1"],
        },
    ],
    "signoff": "Sincerely,",
}


def _letter(**kwargs) -> CoverLetter:
    return CoverLetter.model_validate({**LETTER, **kwargs})


# ---------------------------------------------------------------- gate ----


def test_a_grounded_letter_passes(example_profile):
    assert check_letter(_letter(), example_profile, example_profile.sources()) == []


def test_enthusiasm_that_becomes_a_claim_is_blocked(example_profile):
    """The whole reason a letter goes through the gate: "passionate about Kubernetes" is
    fine, "ran it on Kubernetes" is a claim, and the two are one word apart."""
    letter = _letter(
        paragraphs=[{"text": "I have run production Kubernetes clusters for three years.",
                     "source_ids": ["exp-northwind-backend.h1"]}]
    )
    kinds = {v.kind for v in check_letter(letter, example_profile, example_profile.sources())}
    assert "unsupported_term" in kinds


def test_an_uncited_paragraph_is_blocked(example_profile):
    letter = _letter(paragraphs=[{"text": "I would be a great fit.", "source_ids": []}])
    kinds = [v.kind for v in check_letter(letter, example_profile, example_profile.sources())]
    assert kinds == ["uncited_bullet"]


def test_an_empty_letter_is_blocked(example_profile):
    assert [v.kind for v in check_letter(_letter(paragraphs=[]), example_profile, {})] == ["empty_letter"]


def test_the_company_you_are_writing_to_is_not_a_claim_about_you(example_profile):
    """Applying to DeepMind must not fail every draft: a CamelCase company name is
    indistinguishable from a CamelCase product name to the term rule."""
    jd = JobDescription(raw="", company="DeepMind", title="Research Engineer")
    letter = _letter(
        paragraphs=[{"text": "DeepMind's data platform is the kind of system I rewrote at "
                             "Northwind, cutting a nightly job from 51 minutes to 9.",
                     "source_ids": ["exp-northwind-backend.h1"]}]
    )
    index = example_profile.sources()
    assert [v.kind for v in check_letter(letter, example_profile, index)] == ["unsupported_term"]
    assert check_letter(letter, example_profile, index, allowed_terms=allowed_terms(jd)) == []


# -------------------------------------------------------------- prompt ----


def test_the_addressee_falls_back_to_a_convention_not_a_guess():
    """PLAN.md open question 4. Guessing a name off a company page is how a letter ends up
    addressed to someone who left."""
    assert addressee_for(JobDescription(raw=""), CFG) == "Hiring Manager"


def test_paragraph_budget_tracks_the_word_budget():
    assert paragraph_budget(150) == 3  # floored: opening, middle, close
    assert paragraph_budget(300) == 4
    assert paragraph_budget(1000) == 5  # capped


def test_the_prompt_states_the_rule_that_separates_enthusiasm_from_a_claim(example_profile):
    system, user = build_prompt(example_profile, POSTING, None, CFG)
    assert "Enthusiasm is not evidence" in system
    assert "DECLARED SKILLS" in user
    assert "do not praise the" in user
    # The two things the prompt is actually for, both of which letter_review.py then checks
    # rather than trusting: the opening, and the vocabulary that reads as machine-written.
    assert '"I am writing to..."' in user
    assert "delve" in user
    assert CFG.COVER_LETTER_TONE in user


def test_write_fills_in_the_addressee_the_model_left_out(example_profile):
    letter = write(example_profile, POSTING, None, CFG,
                   lambda s, u: {"paragraphs": [{"text": "x", "source_ids": []}]})
    assert letter.addressee == "Hiring Manager"


def test_write_rejects_a_letter_of_the_wrong_shape(example_profile):
    with pytest.raises(LLMError, match="does not fit the schema"):
        write(example_profile, POSTING, None, CFG, lambda s, u: {"paragraphs": "one long string"})


# ---------------------------------------------------------- round trip ----


@needs_chromium
def test_every_paragraph_survives_the_pdf(example_profile, tmp_path):
    letter = _letter()
    rendered = render_cover_letter(letter, example_profile, tmp_path, CFG)
    report = verify_letter(rendered.pdf_path, letter, example_profile,
                           page_count=rendered.page_count)

    assert report.missing == []
    assert report.page_count == 1
    assert report.checks["name"] and report.checks["addressee"]


@needs_chromium
def test_the_letter_carries_the_date_and_the_signature(example_profile, tmp_path):
    rendered = render_cover_letter(_letter(), example_profile, tmp_path, CFG)
    html = rendered.html_path.read_text(encoding="utf-8")
    assert "Dear Hiring Manager," in html
    assert "Sincerely," in html
    assert "Ada Lovelace" in html


@needs_chromium
def test_verification_fails_when_a_paragraph_did_not_make_it(example_profile, tmp_path):
    rendered = render_cover_letter(_letter(), example_profile, tmp_path, CFG)
    claimed = _letter(paragraphs=[{"text": "A paragraph never rendered.", "source_ids": []}])
    report = verify_letter(rendered.pdf_path, claimed, example_profile)
    assert not report.ok
    assert any("never rendered" in item for item in report.missing)


def test_word_count_is_the_body_only():
    assert _letter(paragraphs=[{"text": "one two three", "source_ids": []}]).word_count() == 3
    assert Paragraph(text="x").source_ids == []
