"""The résumé-PDF seeder, exercised against PDFs produced by the same engine the tool
renders with. Parsing a PDF's text layer is nothing like parsing its markup, so these
tests build real files rather than stubbing extraction."""

import pytest
from conftest import needs_chromium

from resume_fill.ingest.resume_pdf import Block, classify, scrape, to_profile

_STYLE = """<style>
body{font-family:Georgia,serif;font-size:10.5pt;margin:0.5in;}
h1{font-size:18pt;margin:0;}
h2{font-size:11pt;border-bottom:1px solid #000;margin:12px 0 4px;text-transform:uppercase;}
p{margin:1px 0;}
</style>"""

# Single column, everything in reading order — what an ATS-safe résumé looks like.
CLEAN_RESUME = f"""<html><head><meta charset="utf-8">{_STYLE}</head><body>
<h1>Ada Lovelace</h1>
<p>Brooklyn, NY | (555) 010-1990 | ada@example.com | github.com/example</p>
<h2>Experience</h2>
<p><b>Northwind Analytics</b> | New York, NY | Jun 2025 &ndash; Aug 2025</p>
<p><i>Backend Engineer Intern</i></p>
<p>&bull; Rewrote the nightly ingestion job from a cron script to an asyncio worker pool, cutting the run from 51 minutes to 9.</p>
<p>&bull; Added contract tests around the 14 upstream feeds, which caught 3 silent schema changes.</p>
<p><b>Hunter College IT</b> | New York, NY | Sep 2024 &ndash; May 2025</p>
<p><i>Student Technician</i></p>
<p>&bull; Handled roughly 40 support tickets a week across Windows and macOS lab machines.</p>
<h2>Education</h2>
<p><b>Hunter College, CUNY</b> | Aug 2023 &ndash; May 2027</p>
<p>B.A. Computer Science, GPA: 3.8/4.0</p>
<h2>Skills</h2>
<p>Languages: Python, SQL, C++</p>
<p>Tools: Git, Docker, Linux</p>
</body></html>"""

# The same résumé laid out with a two-column entry header. Chromium emits the right-hand
# column after the bullets, so the dates arrive detached from the entry they describe.
# Word résumés with a right tab stop do the same thing, so this is not a corner case.
SCRAMBLED_RESUME = f"""<html><head><meta charset="utf-8">{_STYLE}
<style>.row{{display:flex;justify-content:space-between;}}</style></head><body>
<h1>Ada Lovelace</h1>
<p>Brooklyn, NY | (555) 010-1990 | ada@example.com</p>
<h2>Experience</h2>
<div class="row"><b>Northwind Analytics</b><span>Jun 2025 &ndash; Aug 2025</span></div>
<p><i>Backend Engineer Intern</i></p>
<p>&bull; Rewrote the nightly ingestion job from a cron script to an asyncio worker pool.</p>
</body></html>"""


# -------------------------------------------------------- the heuristic ----


def test_classify_bullet_glyph():
    assert classify("• Did the thing.", None) == "bullet"


def test_classify_entry_header_by_trailing_date_range():
    assert classify("Northwind Analytics | New York, NY | Jun 2025 – Aug 2025", None) == "header"


def test_classify_prose_containing_a_date_range_is_not_a_header():
    """A bullet that happens to mention a span of years must not split the entry in two."""
    line = "Grew recurring revenue across the 2023 – 2024 fiscal years while holding headcount flat."
    assert classify(line, Block(header=["Acme"])) == "bullet"


def test_classify_long_line_without_a_glyph_is_a_bullet():
    """PDF list markers are drawn, not written into the text layer, so a résumé's bullets
    routinely arrive with no glyph at all. Length is what is left to go on."""
    block = Block(header=["Northwind Analytics"])
    assert classify("Rewrote the nightly ingestion job and cut its runtime by four fifths.", block) == "bullet"


def test_classify_wrapped_fragment_continues_the_previous_bullet():
    block = Block(header=["Acme"], bullets=["Cut the run from 51 minutes to"])
    assert classify("9.", block) == "continuation"


# ------------------------------------------------------------- real PDFs ----


@needs_chromium
def test_scrape_reads_the_contact_block(html_to_pdf):
    result = scrape(html_to_pdf(CLEAN_RESUME, "clean.pdf"))
    assert result.basics.name == "Ada Lovelace"
    assert result.basics.email == "ada@example.com"
    assert result.basics.phone == "(555) 010-1990"
    assert result.basics.location == "Brooklyn, NY"
    assert any("github.com/example" in link.url for link in result.basics.links)


@needs_chromium
def test_to_profile_recovers_entries_dates_and_bullets(html_to_pdf):
    profile, notes = to_profile(html_to_pdf(CLEAN_RESUME, "clean.pdf"))

    assert [e.company for e in profile.experience] == ["Northwind Analytics", "Hunter College IT"]
    first = profile.experience[0]
    assert first.title == "Backend Engineer Intern"
    assert (first.start, first.end) == ("2025-06", "2025-08")
    assert len(first.highlights) == 2
    # The wrapped "...to\n9." fragment has to be rejoined, or the 51-minutes claim loses
    # the number that makes it a claim.
    assert "51 minutes to 9" in first.highlights[0].text
    assert first.highlights[0].id == "exp-northwind-analytics-backend-engineer.h1"

    assert profile.education[0].institution == "Hunter College, CUNY"
    assert profile.education[0].gpa == "3.8/4.0"
    assert profile.skills["Languages"] == ["Python", "SQL", "C++"]
    assert profile.skills["Tools"] == ["Git", "Docker", "Linux"]
    assert notes == []


@needs_chromium
def test_two_column_header_still_yields_one_entry_with_its_dates(html_to_pdf):
    """The dates arrive after the bullets. They must attach to the entry above rather than
    opening a phantom second job with no company in it."""
    profile, _ = to_profile(html_to_pdf(SCRAMBLED_RESUME, "scrambled.pdf"))
    assert len(profile.experience) == 1
    entry = profile.experience[0]
    assert entry.company == "Northwind Analytics"
    assert entry.start == "2025-06"
    assert len(entry.highlights) == 1


@needs_chromium
def test_empty_pdf_names_the_real_problem(html_to_pdf):
    with pytest.raises(RuntimeError, match="scan"):
        scrape(html_to_pdf("<html><body></body></html>", "blank.pdf"))
