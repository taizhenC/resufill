from resume_fill.bootstrap import audit, bootstrap, merge
from resume_fill.ingest.linkedin import load_export
from resume_fill.profile import Basics, Experience, Highlight, Profile


def _profile(**kwargs) -> Profile:
    kwargs.setdefault("basics", Basics(name="Ada Lovelace"))
    return Profile(**kwargs)


def test_merge_keeps_the_skeletons_identity_and_takes_the_pdfs_bullets():
    """LinkedIn decides which jobs exist and what they are called; the résumé PDF decides
    what you did there. Bullets written for a recruiter beat an empty export field."""
    skeleton = _profile(
        experience=[
            Experience(
                id="exp-northwind", company="Northwind Analytics, Inc.",
                title="Backend Engineer Intern", start="2025-06", end="2025-08",
            )
        ]
    )
    detail = _profile(
        experience=[
            Experience(
                id="exp-pdf-northwind", company="Northwind Analytics",
                title="Backend Engineer Intern", location="New York, NY",
                highlights=[Highlight(id="exp-pdf-northwind.h1", text="Cut the run to 9 minutes.")],
            )
        ]
    )
    merged = merge(skeleton, detail)

    assert len(merged.experience) == 1
    entry = merged.experience[0]
    assert entry.id == "exp-northwind"
    assert entry.company == "Northwind Analytics, Inc."
    assert entry.start == "2025-06"  # the export's dates survive
    assert entry.location == "New York, NY"  # the PDF fills what the export left blank
    # Highlights are renumbered into the surviving entry's namespace, or the id would point
    # at an entry that no longer exists and every bullet citing it would fail grounding.
    assert [h.id for h in entry.highlights] == ["exp-northwind.h1"]
    assert entry.highlights[0].text == "Cut the run to 9 minutes."


def test_merge_appends_jobs_only_the_pdf_knew_about():
    skeleton = _profile(experience=[Experience(id="exp-a", company="Acme", title="Engineer")])
    detail = _profile(experience=[Experience(id="exp-b", company="Globex", title="Analyst")])
    assert [e.company for e in merge(skeleton, detail).experience] == ["Acme", "Globex"]


def test_merge_prefers_the_resumes_skill_categories():
    """A curated Languages/Frameworks/Tools split is a judgement LinkedIn's flat
    endorsement list cannot reproduce, so it wins — but nothing is dropped."""
    skeleton = _profile(skills={"Skills": ["Python", "Kubernetes"]})
    detail = _profile(skills={"Languages": ["Python", "SQL"]})
    merged = merge(skeleton, detail).skills
    assert merged["Languages"] == ["Python", "SQL"]
    assert merged["Skills"] == ["Kubernetes"]


def test_merge_does_not_lose_the_name_to_a_pdf_placeholder():
    skeleton = _profile(basics=Basics(name="Ada Lovelace", email=""))
    detail = _profile(basics=Basics(name="TODO your name", email="ada@example.com"))
    basics = merge(skeleton, detail).basics
    assert basics.name == "Ada Lovelace"
    assert basics.email == "ada@example.com"


def test_audit_names_what_still_needs_a_human():
    thin = _profile(basics=Basics(name="TODO your name"), experience=[
        Experience(id="exp-a", company="Acme", title="Engineer")
    ])
    todo = " | ".join(audit(thin))
    assert "basics.name" in todo
    assert "basics.email" in todo
    assert "exp-a: no bullets" in todo
    assert "exp-a: no start date" in todo
    assert "skills is empty" in todo


def test_audit_is_quiet_on_a_complete_profile(example_profile):
    assert audit(example_profile) == []


def test_bootstrap_from_the_export_alone(linkedin_export):
    profile, used, notes = bootstrap(linkedin_export, None)
    assert profile.basics.name == "Ada Lovelace"
    assert len(used) == 1 and "LinkedIn export" in used[0]
    assert notes == []


def test_bootstrap_with_no_seeds_at_all_says_what_to_do(tmp_path):
    import pytest

    with pytest.raises(RuntimeError, match="--linkedin-export"):
        bootstrap(None, None)


def test_export_only_bootstrap_still_produces_citable_bullets(linkedin_export):
    """A profile whose entries have no highlights cannot be cited, so the export's
    descriptions have to survive the trip."""
    profile = load_export(linkedin_export)
    index = profile.sources()
    assert "Rewrote the nightly ingestion job." in index[f"{profile.experience[0].id}.h1"].text
