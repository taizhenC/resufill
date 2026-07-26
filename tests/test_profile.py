import pytest
from pydantic import ValidationError

from resume_fill.profile import (
    Profile,
    ProfileError,
    dump_profile,
    format_range,
    load_profile,
)
from resume_fill.source import supporting_text


def test_example_profile_is_valid(example_profile):
    assert example_profile.basics.name == "Ada Lovelace"
    assert len(example_profile.experience) == 2
    assert example_profile.experience[0].highlights[0].id == "exp-northwind-backend.h1"


def test_format_range_treats_empty_end_as_present():
    assert format_range("2025-06", "2025-08") == "Jun 2025 – Aug 2025"
    assert format_range("2025-01", "") == "Jan 2025 – Present"
    # Hand-written values survive untouched, so editing the file by hand is not a trap.
    assert format_range("Summer 2024", "") == "Summer 2024 – Present"


def test_sorted_experience_puts_current_roles_first(example_profile):
    order = [e.id for e in example_profile.sorted_experience()]
    assert order == ["exp-northwind-backend", "exp-campus-it"]


def test_sources_index_covers_entries_highlights_and_skills(example_profile):
    index = example_profile.sources()
    assert "exp-northwind-backend" in index
    assert "exp-northwind-backend.h1" in index
    assert "proj-tidepool" in index
    assert "edu-hunter-cs" in index
    assert "cert-aws-cloud-practitioner" in index
    assert "skills" in index


def test_citing_a_job_covers_its_own_bullets_but_not_another_job(example_profile):
    index = example_profile.sources()
    text = supporting_text(index, ["exp-northwind-backend"])
    assert "asyncio worker pool" in text
    assert "support tickets" not in text


def test_all_skills_merges_declared_and_per_highlight_skills(example_profile):
    skills = {s.casefold() for s in example_profile.all_skills()}
    assert "python" in skills  # declared in the skills block
    assert "asyncio" in skills  # only ever tagged on a highlight
    assert "noaa" in skills


def test_load_profile_reports_a_missing_file_with_the_fix(tmp_path):
    with pytest.raises(ProfileError, match="resume-fill init"):
        load_profile(tmp_path / "nope.yaml")


def test_load_profile_rejects_a_profile_without_a_person(tmp_path):
    path = tmp_path / "profile.yaml"
    path.write_text("experience: []\n", encoding="utf-8")
    with pytest.raises(ProfileError, match="does not match the profile schema"):
        load_profile(path)


def test_dump_then_load_round_trips(example_profile, tmp_path):
    path = tmp_path / "profile.yaml"
    dump_profile(example_profile, path, note="hello")
    assert "# hello" in path.read_text(encoding="utf-8")
    assert load_profile(path) == example_profile


def test_profile_requires_a_name():
    with pytest.raises(ValidationError):
        Profile.model_validate({"basics": {}})
