from resume_fill.ingest.linkedin import IdMaker, load_export, parse_date, split_description


def test_parse_date_handles_every_shape_linkedin_emits():
    assert parse_date("Jun 2025") == "2025-06"
    assert parse_date("June 2025") == "2025-06"
    assert parse_date("06/2025") == "2025-06"
    assert parse_date("2025-6-01") == "2025-06"
    assert parse_date("2025") == "2025"
    assert parse_date("") == ""


def test_split_description_strips_bullet_glyphs():
    text = "• Rewrote the job.\n- Added tests.\n\nx\nShipped it."
    assert split_description(text) == ["Rewrote the job.", "Added tests.", "Shipped it."]


def test_id_maker_is_readable_and_unique():
    ids = IdMaker()
    assert ids.make("exp", "Northwind Analytics", "Backend Engineer") == "exp-northwind-analytics-backend-engineer"
    first = ids.make("exp", "Acme")
    assert ids.make("exp", "Acme") == f"{first}-2"


def test_load_export_reads_the_archive(linkedin_export):
    profile = load_export(linkedin_export)

    assert profile.basics.name == "Ada Lovelace"
    assert profile.basics.location == "Brooklyn, New York"
    assert profile.basics.links[0].url == "https://example.com"

    # Two confirmed addresses, one marked Primary — that is the one to use.
    assert profile.basics.email == "ada@example.com"
    assert profile.basics.phone == "(555) 010-1990"

    assert [e.company for e in profile.experience] == ["Northwind Analytics", "Hunter College IT"]
    first = profile.experience[0]
    assert (first.start, first.end) == ("2025-06", "2025-08")
    assert [h.text for h in first.highlights] == [
        "Rewrote the nightly ingestion job.",
        "Added contract tests.",
    ]
    assert first.highlights[0].id == f"{first.id}.h1"

    assert profile.education[0].degree == "B.A. Computer Science"
    assert profile.projects[0].url == "https://github.com/example/tidepool"
    assert profile.certifications[0].issuer == "Amazon Web Services"
    assert profile.skills == {"Skills": ["Python", "PostgreSQL"]}


def test_load_export_survives_the_notes_preamble(linkedin_export):
    """Older archives put a "Notes:" block above the real header row. Reading that as the
    header would silently produce an empty Positions list, which is the worst outcome:
    a profile that looks fine and has no jobs in it."""
    assert len(load_export(linkedin_export).experience) == 2


def test_load_export_tolerates_a_missing_archive(tmp_path):
    profile = load_export(tmp_path / "not-there")
    assert profile.basics.name.startswith("TODO")
    assert profile.experience == []
