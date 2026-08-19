"""The machine-readability rubric.

Two things are being asserted here, and the second matters more than the first:

  1. Each check finds the thing it is for.
  2. The split holds. A parsing failure is a fact about whether the document can be read at
     all; a reading failure is an opinion about whether it is any good. Only the first kind
     is ever allowed near a build failure, because this tool makes exactly one guarantee and
     diluting it with style advice would make it mean less.
"""

import pytest

from resume_fill.ats import DATE_RANGE, review
from resume_fill.document import Bullet, ResumeDoc, SelectedEntry


def _doc(*bullets: str, **kwargs) -> ResumeDoc:
    return ResumeDoc(
        experience=[
            SelectedEntry(
                source_id="exp-northwind-backend",
                bullets=[Bullet(text=t, source_ids=["exp-northwind-backend.h1"]) for t in bullets],
            )
        ],
        **kwargs,
    )


def _check(report, name):
    return next(c for c in report.checks if c.name == name)


GOOD = "Rewrote the nightly ingestion job as an asyncio worker pool, cutting the run from 51 minutes to 9."
ALSO_GOOD = "Added contract tests around the 14 upstream feeds, catching 3 silent schema changes."


def test_a_well_formed_resume_passes_everything(example_profile):
    report = review(_doc(GOOD, ALSO_GOOD), example_profile)
    assert report.ok
    assert report.failed == []


# ------------------------------------------------------------------ parsing ----


def test_a_date_a_parser_cannot_read_is_a_parsing_failure(example_profile):
    """"Summer 2024" has no month and "'23" has no century. A parser does not guess — it
    drops the whole range, and the job arrives with no dates attached to it."""
    profile = example_profile.model_copy(deep=True)
    profile.experience[0].start = "Summer 2024"
    profile.experience[0].end = "'25"

    check = _check(review(_doc(GOOD), profile), "parseable dates")
    assert not check.ok
    assert check.blocking
    assert "Summer 2024" in check.detail


def test_the_date_pattern_accepts_what_the_profile_actually_emits():
    assert DATE_RANGE.match("Jun 2025 – Aug 2025")
    assert DATE_RANGE.match("Jun 2025 – Present")
    assert DATE_RANGE.match("Present")
    assert not DATE_RANGE.match("Summer 2024 – Present")
    assert not DATE_RANGE.match("2024 – 2025")
    assert not DATE_RANGE.match("06/2024 - 08/2025")


def test_a_missing_email_is_a_parsing_failure_and_a_missing_phone_is_not(example_profile):
    """Without an email the parsed record has no key to attach the résumé to a person. A
    missing phone is a field left empty, which is untidy rather than broken."""
    profile = example_profile.model_copy(deep=True)
    profile.basics.email = ""
    profile.basics.phone = ""

    report = review(_doc(GOOD), profile)
    assert _check(report, "email address present").blocking
    assert not _check(report, "email address present").ok
    assert not _check(report, "phone and location present").blocking
    assert not report.ok  # the email alone is enough


def test_a_two_column_template_is_caught(example_profile):
    """Measured, not assumed — see the header of resume.css. A flush-right date column puts
    every date in the document together at the end of the extracted text, detached from the
    job it belongs to. The renderer does not do this; TEMPLATES_DIR means somebody could."""
    html = '<div class="entry" style="display: flex">…</div>'
    check = _check(review(_doc(GOOD), example_profile, html=html), "single column, no tables or images")
    assert not check.ok
    assert check.blocking
    assert "flex container" in check.detail


@pytest.mark.parametrize(
    "markup, expected",
    [
        ("<table><tr><td>x</td></tr></table>", "a table"),
        ("<div style='float: left'>x</div>", "a float"),
        ("<img src='data:image/png;base64,x'>", "an image"),
        ("<p style='position: absolute'>x</p>", "absolute positioning"),
    ],
)
def test_every_layout_that_reorders_the_text_layer_is_caught(example_profile, markup, expected):
    check = _check(
        review(_doc(GOOD), example_profile, html=markup), "single column, no tables or images"
    )
    assert not check.ok and expected in check.detail


def test_the_real_template_passes_its_own_check(example_profile, tmp_path):
    """The check would be worth nothing if the shipped template failed it."""
    from resume_fill.config import Settings
    from resume_fill.render import render_html

    html = render_html(_doc(GOOD, ALSO_GOOD), example_profile, Settings(OUT_DIR=tmp_path))
    assert _check(review(_doc(GOOD), example_profile, html=html), "single column, no tables or images").ok


# ------------------------------------------------------------------ reading ----


def test_a_bullet_that_opens_on_filler_is_advisory_not_blocking(example_profile):
    """"Responsible for the ingestion pipeline" describes a job advert. It is a weaker
    résumé, not an unreadable one, and failing a build over it would put style advice behind
    the one guarantee this tool actually makes."""
    report = review(_doc("Responsible for the nightly ingestion pipeline and its 14 feeds."), example_profile)
    check = _check(report, "bullets lead with what was done")

    assert not check.ok
    assert not check.blocking
    assert report.ok  # advisory failures never make the document un-shippable


def test_a_page_of_unquantified_bullets_is_flagged(example_profile):
    report = review(_doc("Improved the ingestion pipeline.", "Maintained the test suite."), example_profile)
    check = _check(report, "bullets carry numbers")

    assert not check.ok and not check.blocking
    assert "0 of 2" in check.detail


def test_the_quantification_bar_is_a_share_not_a_requirement(example_profile):
    """Half the bullets carrying a figure is the bar. Every bullet carrying one would be a
    demand the record usually cannot meet, and the gate will not let a number be invented to
    meet it."""
    report = review(_doc(GOOD, "Maintained the test suite."), example_profile)
    assert _check(report, "bullets carry numbers").ok


def test_first_person_is_flagged(example_profile):
    check = _check(review(_doc("I rewrote the ingestion job in 9 minutes."), example_profile),
                   "no first-person pronouns")
    assert not check.ok and not check.blocking


def test_an_ordinary_word_containing_a_pronoun_is_not_a_pronoun(example_profile):
    assert _check(
        review(_doc("Migrated 14 internal services onto a shared image."), example_profile),
        "no first-person pronouns",
    ).ok


def test_feedback_names_the_fix_not_just_the_failure(example_profile):
    """A retry prompt that only says "that was wrong" gets the same answer back."""
    from resume_fill.ats import feedback

    text = feedback(review(_doc("Responsible for the pipeline."), example_profile))
    assert "bullets lead with what was done" in text
    assert "Start with the verb" in text


def test_feedback_is_empty_when_there_is_nothing_to_say(example_profile):
    from resume_fill.ats import feedback

    assert feedback(review(_doc(GOOD, ALSO_GOOD), example_profile)) == ""


# ------------------------------------------------------------------- pages ----


def test_the_page_budget_is_only_checked_when_the_page_count_is_known(example_profile):
    """An absent check must never be scored as a passing one — before the render there is no
    honest answer to "how many pages is it"."""
    names = {c.name for c in review(_doc(GOOD), example_profile).checks}
    assert "fits the page budget" not in names

    report = review(_doc(GOOD), example_profile, page_count=2, max_pages=1)
    check = _check(report, "fits the page budget")
    assert not check.ok and check.blocking
