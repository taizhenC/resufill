"""Three ways a text layer can survive extraction and still be unreadable.

The round trip in verify.py asserts every bullet is *there*. These assert that what is there
is actually the words. All three failures are silent — the PDF looks perfect on screen, every
string is present, and a parser reads something else.

The last test is the one that matters most: it renders with the shipped template and asserts
the text layer is clean, because a check that the shipped output cannot pass is worse than no
check at all.
"""

from pathlib import Path

from conftest import needs_chromium

from resume_fill.config import Settings
from resume_fill.document import Bullet, ResumeDoc, SelectedEntry
from resume_fill.render import render_resume
from resume_fill.verify import extract_text, text_layer_artefacts, verify


def _doc(*texts: str) -> ResumeDoc:
    return ResumeDoc(
        experience=[
            SelectedEntry(
                source_id="exp-northwind-backend",
                bullets=[Bullet(text=t, source_ids=["exp-northwind-backend.h1"]) for t in texts],
            )
        ],
        skills={"Languages": ["Python"]},
    )


def test_a_ligature_presentation_form_is_caught():
    """Chromium printing to PDF can emit the codepoint for the ligature glyph rather than the
    letters behind it, so "efficient" arrives as "e<U+FB03>cient" and a recruiter searching
    the whole word does not find it. Nothing about the page looks wrong."""
    found = text_layer_artefacts("Rewrote the ineﬃcient nightly workﬂow")
    assert len(found) == 1
    assert "U+FB02" in found[0] and "U+FB03" in found[0]


def test_a_private_use_codepoint_is_caught():
    """A glyph drawn with no Unicode behind it — an icon font, or a subset with a broken
    ToUnicode map. It renders; it does not extract."""
    found = text_layer_artefacts("Brooklyn, NY  ada@example.com")
    assert found and "private-use" in found[0]


def test_letters_extracted_separately_are_caught():
    """pdfminer inserts a space wherever the inter-glyph gap exceeds its word margin, so a
    tracked-out heading arrives as separate letters. Greenhouse lists this first among the
    things that make a résumé unparseable."""
    found = text_layer_artefacts("S K I L L S\nPython, SQL")
    assert found and "letters extracted separately" in found[0]


def test_ordinary_initials_are_not_a_failure():
    """Four would catch "U S A" and an initialled name, which are ordinary things to write.
    Failing a build over them would be worse than the thing being guarded against."""
    assert text_layer_artefacts("Worked with the U S A team on the J R R project") == []


def test_a_clean_text_layer_reports_nothing():
    assert text_layer_artefacts("Rewrote the nightly ingestion job as an asyncio worker pool") == []


# ------------------------------------------------------------------ real PDFs ----


@needs_chromium
def test_the_shipped_template_produces_a_clean_text_layer(example_profile, tmp_path):
    """The one that matters. A check the shipped output cannot pass is worse than no check.

    The bullet is chosen to contain every ligature pair Chromium might substitute — ff, fi,
    fl, ffi, ffl — because that substitution is the failure this asserts against.
    """
    doc = _doc(
        "Rewrote the inefficient nightly workflow, which affected office staff and "
        "shuffled 51 files a night.",
    )
    rendered = render_resume(doc, example_profile, tmp_path, Settings(OUT_DIR=tmp_path))
    raw = extract_text(rendered.pdf_path)

    assert text_layer_artefacts(raw) == []
    # And the words themselves survived as words, which is the point of the assertion above.
    assert "inefficient" in raw and "workflow" in raw and "shuffled" in raw


@needs_chromium
def test_the_contact_block_lands_at_the_top(example_profile, tmp_path):
    """A parser looks at the top for it. Textkernel raises a Major Issue for a contact
    section found anywhere else — the name arriving after the first job is a name the parsed
    record may not get."""
    doc = _doc("Rewrote the nightly ingestion job as an asyncio worker pool.")
    rendered = render_resume(doc, example_profile, tmp_path, Settings(OUT_DIR=tmp_path))
    report = verify(rendered.pdf_path, doc, example_profile, page_count=rendered.page_count)

    assert report.ok
    assert report.checks["contact block is at the top"]
    assert report.checks["text layer is clean"]


@needs_chromium
def test_letter_spacing_in_a_template_override_would_be_caught(example_profile, tmp_path):
    """TEMPLATES_DIR lets a user replace the stylesheet, and this is the change that looks
    like typography and reads as corruption. Rendered rather than asserted, because whether
    a given tracking splits the glyphs is a fact about the renderer."""
    templates = tmp_path / "templates"
    templates.mkdir()
    shipped = Path(__file__).resolve().parents[1] / "resume_fill" / "templates"
    (templates / "resume.html.j2").write_text(
        (shipped / "resume.html.j2").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (templates / "resume.css").write_text(
        (shipped / "resume.css").read_text(encoding="utf-8").replace(
            "  letter-spacing: 0;\n  border-bottom", "  letter-spacing: 1em;\n  border-bottom"
        ),
        encoding="utf-8",
    )

    cfg = Settings(OUT_DIR=tmp_path, TEMPLATES_DIR=templates)
    rendered = render_resume(_doc("Rewrote the nightly ingestion job."), example_profile, tmp_path, cfg)
    artefacts = text_layer_artefacts(extract_text(rendered.pdf_path))

    assert artefacts, "1em of tracking on the section headings should split them"
    assert "letters extracted separately" in artefacts[0]
