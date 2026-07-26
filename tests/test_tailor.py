import pytest

from resume_fill.evidence import Corpus, EvidenceItem
from resume_fill.jd import parse_deterministic
from resume_fill.llm import LLMError
from resume_fill.tailor import build_prompt, bullet_budget, catalogue, tailor

JD = parse_deterministic("Backend Engineer\n\nRequirements\n- Python\n- PostgreSQL\n")

GOOD_RESPONSE = {
    "headline": "Backend engineer — data pipelines",
    "summary": "",
    "experience": [
        {
            "source_id": "exp-northwind-backend",
            "bullets": [{"text": "Rewrote the nightly ingestion job.", "source_ids": ["exp-northwind-backend.h1"]}],
        }
    ],
    "skills": {"Languages": ["Python"]},
    "section_order": ["skills", "experience"],
}


def test_catalogue_lists_every_citable_id(example_profile):
    """The model has to copy these ids back verbatim; anything it must reconstruct it will
    eventually reconstruct wrong."""
    text = catalogue(example_profile)
    assert "[exp-northwind-backend]" in text
    assert "[exp-northwind-backend.h1]" in text
    assert "[proj-tidepool]" in text
    assert "[edu-hunter-cs]" in text
    assert "[cert-aws-cloud-practitioner]" in text
    assert "DECLARED SKILLS" in text


def test_catalogue_carries_the_facts_that_back_a_claim(example_profile):
    text = catalogue(example_profile)
    assert "51 minutes to 9" in text
    assert "skills: Python, asyncio, PostgreSQL" in text


def test_catalogue_marks_blog_evidence_as_narrative_only(example_profile):
    """A blog post has no employer and no dates, so it must never be selectable as an
    entry — only citable inside one."""
    corpus = Corpus(items=[EvidenceItem(id="blog:async#1", title="Async ingestion", text="I used trio.")])
    text = catalogue(example_profile, corpus)
    assert "[blog:async#1]" in text
    assert "never as an entry of its own" in text


def test_prompt_states_the_rules_the_validator_will_enforce(example_profile):
    system, user = build_prompt(example_profile, JD, None)
    assert "rejects the document if any claim cannot be traced" in system
    assert "Do not write company names, job titles or dates" in user
    assert "must be a subset of DECLARED SKILLS" in user
    assert "Python" in user  # the posting's requirements reached the prompt


def test_prompt_carries_the_rejection_reason_on_a_retry(example_profile):
    _, user = build_prompt(example_profile, JD, None, feedback="- [unsupported_number] 94% is invented")
    assert "WHY THE LAST ATTEMPT WAS REJECTED" in user
    assert "94% is invented" in user


def test_bullet_budget_scales_with_the_page_cap():
    assert bullet_budget(1) < bullet_budget(2)
    assert bullet_budget(0) >= 6


def test_tailor_parses_the_document(example_profile):
    doc = tailor(example_profile, JD, None, lambda system, user: GOOD_RESPONSE)
    assert doc.experience[0].source_id == "exp-northwind-backend"
    assert doc.experience[0].bullets[0].source_ids == ["exp-northwind-backend.h1"]
    assert doc.skills == {"Languages": ["Python"]}
    # Sections the model forgot are appended rather than silently dropped.
    assert doc.ordered_sections()[:2] == ["skills", "experience"]
    assert "education" in doc.ordered_sections()


def test_tailor_rejects_a_document_of_the_wrong_shape(example_profile):
    """A malformed document is not a grounding failure and must not be fed back as one, or
    the loop spends its whole budget re-litigating a JSON shape."""
    with pytest.raises(LLMError, match="does not fit the schema"):
        tailor(example_profile, JD, None, lambda system, user: {"experience": "lots"})
