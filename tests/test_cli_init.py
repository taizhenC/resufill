from conftest import needs_chromium
from test_ingest_resume_pdf import CLEAN_RESUME

from resume_fill.cli import main
from resume_fill.profile import load_profile


@needs_chromium
def test_init_merges_both_seeds_into_one_profile(linkedin_export, html_to_pdf, tmp_path, capsys):
    pdf = html_to_pdf(CLEAN_RESUME, "clean.pdf")
    out = tmp_path / "profile.yaml"

    code = main(["init", "--linkedin-export", str(linkedin_export), "--resume-pdf", str(pdf),
                 "--out", str(out)])
    assert code == 0

    profile = load_profile(out)
    assert profile.basics.name == "Ada Lovelace"
    assert profile.basics.email == "ada@example.com"
    # The export named the jobs; the PDF supplied the bullets that make them citable.
    assert [e.company for e in profile.experience] == ["Northwind Analytics", "Hunter College IT"]
    assert "51 minutes to 9" in profile.experience[0].highlights[0].text
    assert profile.skills["Languages"] == ["Python", "SQL", "C++"]

    printed = capsys.readouterr().out
    assert "read LinkedIn export" in printed
    assert str(out) in printed


def test_init_refuses_to_clobber_an_edited_profile(linkedin_export, tmp_path, capsys):
    """profile.yaml is hand-corrected by design. Overwriting it silently would throw away
    the only work in this tool that a human has to do."""
    out = tmp_path / "profile.yaml"
    assert main(["init", "--linkedin-export", str(linkedin_export), "--out", str(out)]) == 0
    out.write_text(out.read_text(encoding="utf-8") + "\n# my edits\n", encoding="utf-8")

    assert main(["init", "--linkedin-export", str(linkedin_export), "--out", str(out)]) == 1
    assert "--force" in capsys.readouterr().out
    assert "# my edits" in out.read_text(encoding="utf-8")

    assert main(["init", "--linkedin-export", str(linkedin_export), "--out", str(out), "--force"]) == 0
    assert "# my edits" not in out.read_text(encoding="utf-8")


def test_init_with_nothing_to_read_fails_loudly(tmp_path, capsys):
    code = main(["init", "--linkedin-export", str(tmp_path / "nope"), "--out", str(tmp_path / "p.yaml")])
    assert code == 1
    assert "nothing to bootstrap from" in capsys.readouterr().out


def test_init_reports_what_still_needs_correcting(linkedin_export, tmp_path, capsys):
    main(["init", "--linkedin-export", str(linkedin_export), "--out", str(tmp_path / "profile.yaml")])
    printed = capsys.readouterr().out
    # The export gives Hunter College IT no description at all, so that entry has nothing
    # citable and `init` has to say so rather than let it fail silently at generation time.
    assert "no bullets" in printed
