"""Render a real PDF and read it back.

Every test here that touches a PDF goes through Chromium and pdfminer, because the whole
point of this milestone is that a PDF's text layer is not its markup.
"""

import pytest
from conftest import needs_chromium

from resume_fill.config import Settings
from resume_fill.document import Bullet, ResumeDoc, SelectedEntry
from resume_fill.render import RenderError, build_context, render_html, render_resume
from resume_fill.verify import flatten, verify

CFG = Settings()


def _doc(**kwargs) -> ResumeDoc:
    base = dict(
        headline="Backend engineer — data pipelines",
        experience=[
            SelectedEntry(
                source_id="exp-northwind-backend",
                bullets=[
                    Bullet(
                        text="Rewrote the nightly ingestion job as an asyncio worker pool, cutting the "
                        "run from 51 minutes to 9.",
                        source_ids=["exp-northwind-backend.h1"],
                    ),
                    Bullet(
                        text="Added contract tests around the 14 upstream feeds, catching 3 silent "
                        "schema changes in the first month.",
                        source_ids=["exp-northwind-backend.h2"],
                    ),
                ],
            )
        ],
        projects=[
            SelectedEntry(
                source_id="proj-tidepool",
                bullets=[Bullet(text="Packed 40 years of NOAA constants into 6 MB of SQLite.",
                                source_ids=["proj-tidepool.h1"])],
            )
        ],
        education=[
            SelectedEntry(
                source_id="edu-hunter-cs",
                bullets=[Bullet(text="Coursework: Databases, Operating Systems.",
                                source_ids=["edu-hunter-cs.h1"])],
            )
        ],
        skills={"Languages": ["Python", "SQL"], "Data": ["PostgreSQL"]},
    )
    base.update(kwargs)
    return ResumeDoc(**base)


# ----------------------------------------------------------- context ----


def test_facts_come_from_the_profile_not_the_document(example_profile):
    """The tailor selects an id; the company, title and dates are looked up. A fact the
    model never writes is a fact that can never be wrong."""
    context = build_context(_doc(), example_profile, CFG)
    experience = next(s for s in context["sections"] if s["title"] == "Experience")
    entry = experience["entries"][0]
    assert entry["primary"] == "Northwind Analytics"
    assert [p["text"] for p in entry["parts"]] == [
        "Backend Engineer Intern", "New York, NY", "Jun 2025 – Aug 2025"
    ]


def test_empty_sections_are_dropped_not_rendered_blank(example_profile):
    context = build_context(_doc(projects=[], education=[], skills={}), example_profile, CFG)
    assert [s["title"] for s in context["sections"]] == ["Experience"]


def test_section_order_follows_the_document(example_profile):
    doc = _doc(section_order=["skills", "education", "experience", "projects"])
    context = build_context(doc, example_profile, CFG)
    assert [s["title"] for s in context["sections"]] == [
        "Skills", "Education", "Experience", "Projects"
    ]


def test_a_selection_the_profile_no_longer_has_is_skipped(example_profile):
    """ground.py rejects this long before render; skipping rather than raising keeps the
    renderer usable for debugging a rejected draft."""
    doc = _doc(experience=[SelectedEntry(source_id="exp-gone", bullets=[Bullet(text="x", source_ids=[])])])
    context = build_context(doc, example_profile, CFG)
    assert not any(s["title"] == "Experience" for s in context["sections"])


def test_html_inlines_the_stylesheet(example_profile):
    """set_content() loads the page with no base URL, so a <link> would resolve to nothing
    and the PDF would come out unstyled with no error anywhere."""
    html = render_html(_doc(), example_profile, CFG)
    assert "<style>" in html and "font-family" in html
    assert "<link" not in html


def test_the_stylesheet_is_not_html_escaped(example_profile):
    """Autoescape is on for every other value in the context, and must stay on. Escaping
    the stylesheet turns `font-family: "Helvetica Neue"` into `&#34;Helvetica Neue&#34;`,
    which Chromium discards as invalid and silently falls back to a serif default — a
    failure with no error anywhere, visible only by looking at the PDF."""
    html = render_html(_doc(), example_profile, CFG)
    assert '"Helvetica Neue"' in html
    assert "&#34;" not in html


def test_profile_text_is_still_escaped(example_profile):
    """The exception is the stylesheet only. A company named `Foo & Bar <Ltd>` must not
    become markup."""
    profile = example_profile.model_copy(deep=True)
    profile.basics.name = "Ada <script>alert(1)</script> Lovelace"
    html = render_html(_doc(), profile, CFG)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_html_uses_no_layout_that_reorders_the_text_layer(example_profile):
    """Measured, not assumed: a flexbox two-column entry header extracts with the dates
    after the bullets. Single column is the whole ATS guarantee."""
    html = render_html(_doc(), example_profile, CFG)
    for banned in ("display:flex", "display: flex", "display:grid", "display: grid",
                   "float:", "position:absolute", "position: absolute", "<table"):
        assert banned not in html


def test_an_absent_user_template_dir_falls_back_to_the_packaged_one(example_profile, tmp_path):
    from resume_fill.config import PACKAGE_DIR

    assert (PACKAGE_DIR / "templates").exists()
    assert render_html(_doc(), example_profile, Settings(TEMPLATES_DIR=tmp_path / "nope"))


def test_render_error_when_no_templates_exist_at_all(example_profile, monkeypatch, tmp_path):
    monkeypatch.setattr(Settings, "template_dirs", property(lambda self: [tmp_path / "a"]))
    with pytest.raises(RenderError, match="no template directory"):
        render_html(_doc(), example_profile, Settings())


# -------------------------------------------------------- round trip ----


@needs_chromium
def test_every_bullet_and_heading_survives_the_pdf(example_profile, tmp_path):
    doc = _doc()
    rendered = render_resume(doc, example_profile, tmp_path, CFG)
    report = verify(rendered.pdf_path, doc, example_profile, page_count=rendered.page_count)

    assert report.missing == []
    assert report.ok
    assert report.page_count == 1
    assert report.checks["name"] and report.checks["email"] and report.checks["phone"]
    assert report.checks["heading:Experience"]
    assert all(v for k, v in report.checks.items() if k.startswith("bullet:"))


@needs_chromium
def test_the_dates_stay_attached_to_their_own_job(example_profile, tmp_path):
    """The failure the layout rules exist to prevent: in the extracted text, the employer,
    the title and the dates must still be adjacent."""
    doc = _doc()
    rendered = render_resume(doc, example_profile, tmp_path, CFG)
    text = flatten(verify(rendered.pdf_path, doc, example_profile).text)
    assert "northwind analytics | backend engineer intern | new york, ny | jun 2025 - aug 2025" in text


@needs_chromium
def test_verification_fails_when_a_bullet_did_not_make_it(example_profile, tmp_path):
    """The assertion has to be able to fail, or it guarantees nothing. Render one document
    and verify a different one against the same PDF."""
    rendered = render_resume(_doc(), example_profile, tmp_path, CFG)
    claimed = _doc(
        experience=[
            SelectedEntry(
                source_id="exp-northwind-backend",
                bullets=[Bullet(text="A bullet that was never rendered at all.", source_ids=[])],
            )
        ]
    )
    report = verify(rendered.pdf_path, claimed, example_profile)
    assert not report.ok
    assert any("never rendered" in item for item in report.missing)


@needs_chromium
def test_a_document_that_overruns_its_page_budget_fails(example_profile, tmp_path):
    long_doc = _doc(
        experience=[
            SelectedEntry(
                source_id="exp-northwind-backend",
                bullets=[
                    Bullet(text=f"Bullet number {i} " + "with a lot of words in it " * 12,
                           source_ids=["exp-northwind-backend.h1"])
                    for i in range(1, 40)
                ],
            )
        ]
    )
    rendered = render_resume(long_doc, example_profile, tmp_path, CFG)
    assert rendered.page_count > 1
    report = verify(rendered.pdf_path, long_doc, example_profile, max_pages=1,
                    page_count=rendered.page_count)
    assert not report.ok
    assert any("budget is 1" in item for item in report.missing)
    assert report.checks["page_budget"] is False


@needs_chromium
def test_the_html_is_kept_next_to_the_pdf(example_profile, tmp_path):
    """When a bullet fails the round trip the first question is always whether it made it
    into the HTML."""
    rendered = render_resume(_doc(), example_profile, tmp_path, CFG)
    assert rendered.html_path.exists()
    assert "Rewrote the nightly ingestion job" in rendered.html_path.read_text(encoding="utf-8")


def test_flatten_rejoins_a_word_chromium_hyphenated():
    assert "reconciliation" in flatten("recon-\nciliation")
