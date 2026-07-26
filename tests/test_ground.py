"""The fabrication gate — the module the whole design rests on.

If a claim can slip past here, the auto-iterate loop has a cheap way to raise its score
(invent keywords) and the number it reports stops meaning anything. So these tests are
adversarial: each one is a specific way a model tries to be helpful.
"""

from resume_fill.document import Bullet, ResumeDoc, SelectedEntry
from resume_fill.ground import check, feedback, summarize, unsupported_terms


def _doc(**kwargs) -> ResumeDoc:
    return ResumeDoc(**kwargs)


def _experience(source_id: str, *bullets: tuple[str, list[str]]) -> list[SelectedEntry]:
    return [SelectedEntry(source_id=source_id, bullets=[Bullet(text=t, source_ids=s) for t, s in bullets])]


def test_a_faithful_document_passes(example_profile):
    doc = _doc(
        experience=_experience(
            "exp-northwind-backend",
            (
                "Rewrote the nightly ingestion job as an asyncio worker pool, cutting the run "
                "from 51 minutes to 9.",
                ["exp-northwind-backend.h1"],
            ),
        ),
        skills={"Languages": ["Python", "SQL"]},
    )
    assert check(doc, example_profile, example_profile.sources()) == []


def test_an_invented_number_is_blocked(example_profile):
    """The single most likely fabrication: the source says 51 minutes to 9, the draft says
    "by 90%" because that reads better."""
    doc = _doc(
        experience=_experience(
            "exp-northwind-backend",
            ("Cut nightly ingestion time by 94%.", ["exp-northwind-backend.h1"]),
        )
    )
    violations = check(doc, example_profile, example_profile.sources())
    assert [v.kind for v in violations] == ["unsupported_number"]
    assert "94%" in violations[0].detail


def test_an_invented_technology_is_blocked(example_profile):
    """The posting wants Kubernetes. The record has never seen it. This is the exact
    fabrication the score would otherwise reward."""
    doc = _doc(
        experience=_experience(
            "exp-northwind-backend",
            ("Ran the ingestion workers on Kubernetes.", ["exp-northwind-backend.h1"]),
        )
    )
    violations = check(doc, example_profile, example_profile.sources())
    assert [v.kind for v in violations] == ["unsupported_term"]
    assert unsupported_terms(violations) == ["Kubernetes"]


def test_a_declared_skill_may_be_named_without_the_bullet_citing_it(example_profile):
    """The one concession. Docker is in profile.skills but appears in no highlight."""
    doc = _doc(
        experience=_experience(
            "exp-northwind-backend",
            ("Packaged the ingestion workers with Docker.", ["exp-northwind-backend.h1"]),
        )
    )
    assert check(doc, example_profile, example_profile.sources()) == []


def test_evidence_from_another_job_cannot_be_borrowed(example_profile):
    """Citing the campus IT job does not license a claim about the analytics pipeline —
    parent/child containment, not a flat lookup."""
    doc = _doc(
        experience=_experience(
            "exp-campus-it",
            ("Rewrote the nightly ingestion job in asyncio.", ["exp-campus-it.h1"]),
        )
    )
    kinds = {v.kind for v in check(doc, example_profile, example_profile.sources())}
    assert "unsupported_term" in kinds


def test_an_uncited_bullet_is_blocked(example_profile):
    doc = _doc(experience=_experience("exp-northwind-backend", ("Did excellent work.", [])))
    assert [v.kind for v in check(doc, example_profile, example_profile.sources())] == ["uncited_bullet"]


def test_a_citation_to_an_id_that_does_not_exist_is_blocked(example_profile):
    doc = _doc(
        experience=_experience("exp-northwind-backend", ("Shipped it.", ["exp-northwind-backend.h9"]))
    )
    violations = check(doc, example_profile, example_profile.sources())
    assert [v.kind for v in violations] == ["unknown_source"]
    assert "exp-northwind-backend.h9" in violations[0].detail


def test_selecting_an_entry_that_does_not_exist_is_blocked(example_profile):
    doc = _doc(experience=_experience("exp-google-l7", ("Led the org.", ["exp-google-l7"])))
    kinds = [v.kind for v in check(doc, example_profile, example_profile.sources())]
    assert kinds == ["unknown_entry"]


def test_a_project_cannot_be_promoted_into_employment(example_profile):
    """Placing a side project under Experience invents a job with an employer and dates."""
    doc = _doc(experience=_experience("proj-tidepool", ("Built it.", ["proj-tidepool.h1"])))
    violations = check(doc, example_profile, example_profile.sources())
    assert [v.kind for v in violations] == ["wrong_section"]


def test_the_skills_block_cannot_grow(example_profile):
    """The cheapest place to fabricate, and the easiest to check: it must be a subset."""
    doc = _doc(skills={"Cloud": ["Kubernetes", "Python"]})
    violations = check(doc, example_profile, example_profile.sources())
    assert [v.kind for v in violations] == ["undeclared_skill"]
    assert "Kubernetes" in violations[0].detail


def test_the_summary_is_checked_too(example_profile):
    doc = _doc(
        summary="Backend engineer with 8 years of Kubernetes experience.",
        experience=_experience(
            "exp-northwind-backend", ("Rewrote the ingestion job.", ["exp-northwind-backend.h1"])
        ),
    )
    kinds = {v.kind for v in check(doc, example_profile, example_profile.sources())}
    assert kinds == {"unsupported_number", "unsupported_term"}


def test_selecting_an_entry_without_writing_bullets_is_blocked(example_profile):
    doc = _doc(experience=[SelectedEntry(source_id="exp-northwind-backend")])
    assert [v.kind for v in check(doc, example_profile, example_profile.sources())] == ["empty_entry"]


def test_a_certification_must_exist(example_profile):
    doc = _doc(certification_ids=["cert-cissp"])
    assert [v.kind for v in check(doc, example_profile, example_profile.sources())] == ["unknown_entry"]


def test_feedback_names_the_fix_not_just_the_failure(example_profile):
    """A retry prompt that only says "that was wrong" gets the same answer back."""
    doc = _doc(
        experience=_experience(
            "exp-northwind-backend",
            ("Cut ingestion 94% on Kubernetes.", ["exp-northwind-backend.h1"]),
        )
    )
    text = feedback(check(doc, example_profile, example_profile.sources()))
    assert "REJECTED" in text
    assert "94%" in text and "Kubernetes" in text
    assert "it is a gap" in text  # the instruction not to substitute an invention


def test_feedback_is_empty_when_nothing_is_wrong():
    assert feedback([]) == ""


def test_summarize_counts_by_kind(example_profile):
    doc = _doc(
        experience=_experience(
            "exp-northwind-backend",
            ("Cut it 94% on Kubernetes.", ["exp-northwind-backend.h1"]),
            ("Also 71% faster.", ["exp-northwind-backend.h1"]),
        )
    )
    assert summarize(check(doc, example_profile, example_profile.sources())) == (
        "unsupported_number×2, unsupported_term×1"
    )
