"""The other question about a cover letter.

ground.py asks whether any of it is false. This asks whether any of it is worth reading —
and a letter can pass the first completely while opening "I am writing to express my
interest in the Backend Engineer position", which is the most common first line in the pile
and the specific thing a reader is scanning for.

Two things under test. That each check finds its own failure, and that the blocking /
advisory split holds: only a defect a rewrite reliably fixes is worth a model call.
"""

from test_pipeline import POSTING

from resume_fill.document import CoverLetter, Paragraph
from resume_fill.letter_review import feedback, review

# Roughly the length and shape of a real letter, because most of the checks are about
# length and shape and a 90-word fixture would fail them for reasons the test is not about.
REAL_WORK = (
    "Rewriting a nightly ingestion job as an asyncio worker pool cut its run from 51 minutes "
    "to 9, which is the shape of the problem your data platform team describes. The old "
    "version was a single-threaded cron script that had grown one feed at a time, and most "
    "of the work was untangling what each of those feeds actually assumed about the others "
    "before any of it could run concurrently in Python."
)
MIDDLE = (
    "Contract tests around the 14 upstream feeds caught 3 silent schema changes in the first "
    "month, and the PostgreSQL schema work that followed is the part I would want to keep "
    "doing. Two of those changes would have failed quietly and left a day of partial data "
    "behind them, which is the failure mode that is expensive to notice late. Writing the "
    "tests was straightforward; deciding what a contract between two teams should actually "
    "assert was the interesting part, and it is the reason the posting's line about owning "
    "the ingestion path end to end caught my eye."
)
CLOSE = (
    "tidepool, a side project, packs 40 years of NOAA harmonic constants into a 6 MB SQLite "
    "file so lookups work with no network. It exists because the official tables are only "
    "available online and I wanted them on a boat. I would be glad to talk through either of "
    "these, or about what the first month on your ingestion path would look like."
)


def _letter(*texts: str, addressee: str = "Hiring Manager") -> CoverLetter:
    return CoverLetter(
        addressee=addressee,
        paragraphs=[Paragraph(text=t, source_ids=["exp-northwind-backend.h1"]) for t in texts],
    )


def _check(result, name):
    return next(c for c in result.checks if c.name == name)


GOOD = _letter(REAL_WORK, MIDDLE, CLOSE)


def test_a_specific_letter_passes(example_profile):
    result = review(GOOD, POSTING, example_profile)
    assert result.ok
    assert result.blocking_failures == []


# ----------------------------------------------------------------- opening ----


def test_the_most_common_opening_in_the_pile_is_blocked(example_profile):
    """"I am writing to express my interest in the X position" tells the reader nothing and
    signals a template in the same breath. It is the single highest-value thing to catch."""
    letter = _letter(
        "I am writing to express my interest in the Backend Engineer position at Northwind.",
        MIDDLE, CLOSE,
    )
    check = _check(review(letter, POSTING, example_profile), "opens on something that happened")
    assert not check.ok and check.blocking


def test_enthusiasm_as_an_opening_is_the_same_failure(example_profile):
    for opening in (
        "I am excited to apply for the Backend Engineer role.",
        "I would like to apply for this position.",
        "As a passionate backend engineer, I bring a lot to the table.",
        "Please accept this application for the Backend Engineer opening.",
        "Re: Backend Engineer, Data Platform",
    ):
        letter = _letter(opening, MIDDLE, CLOSE)
        assert not _check(
            review(letter, POSTING, example_profile), "opens on something that happened"
        ).ok, opening


def test_a_sentence_that_merely_starts_with_i_is_not_a_dead_opening(example_profile):
    """The check is about formulas, not about the pronoun. Over-matching here would cost an
    iteration to rewrite a perfectly good first line."""
    letter = _letter(
        "I rewrote a nightly ingestion job as an asyncio worker pool and cut its run from 51 "
        "minutes to 9.",
        MIDDLE, CLOSE,
    )
    assert _check(review(letter, POSTING, example_profile), "opens on something that happened").ok


def test_to_whom_it_may_concern_is_blocked(example_profile):
    letter = _letter(REAL_WORK, MIDDLE, CLOSE, addressee="To Whom It May Concern")
    check = _check(review(letter, POSTING, example_profile), "addressee is a convention, not a shrug")
    assert not check.ok and check.blocking


def test_the_configured_fallback_is_fine(example_profile):
    """"Hiring Manager" is a real convention. Guessing a name off a company page is how a
    letter ends up addressed to somebody who left."""
    assert _check(
        review(GOOD, POSTING, example_profile), "addressee is a convention, not a shrug"
    ).ok


# ------------------------------------------------------------------ shape ----


def test_a_letter_with_no_specifics_is_blocked(example_profile):
    """No figure and no tool in it means a form letter with a company name substituted in.
    The gate guarantees every specific is real, which is what makes them free to insist on."""
    letter = _letter(
        "Building reliable data systems is what I care most about in my work day to day.",
        "I would bring energy and a strong work ethic to this team every single day here.",
        "I would welcome the chance to discuss how I could contribute to what you are doing.",
    )
    check = _check(review(letter, POSTING, example_profile), "carries specifics")
    assert not check.ok and check.blocking


def test_a_letter_that_answers_nothing_the_posting_asked_for_is_blocked(example_profile):
    letter = _letter(
        "Packing 40 years of NOAA harmonic constants into a 6 MB SQLite file is the kind of "
        "problem I enjoy most.",
        "The offline lookup path took some care to get right and it has held up well since.",
        "I would be glad to talk it through whenever suits you.",
    )
    check = _check(review(letter, POSTING, example_profile), "answers this posting")
    assert not check.ok and check.blocking


def test_length_is_a_band_not_a_target(example_profile):
    short = _letter("Cut a nightly job from 51 minutes to 9 with asyncio and PostgreSQL.", "Thanks.",
                    "Regards.")
    assert not _check(review(short, POSTING, example_profile), "fits on a page and says something").ok

    long = _letter(REAL_WORK, MIDDLE * 4, CLOSE)
    assert long.word_count() > 420
    assert not _check(review(long, POSTING, example_profile), "fits on a page and says something").ok


def test_two_paragraphs_is_not_a_letter(example_profile):
    two = _letter(REAL_WORK, MIDDLE)
    assert not _check(
        review(two, POSTING, example_profile), "has an opening, a middle and a close"
    ).ok


# --------------------------------------------------------------- advisory ----


def test_the_machine_written_vocabulary_is_advisory(example_profile):
    """Worth saying; not worth a model call on its own. A letter that says "delve" is a
    slightly worse letter, not a broken one."""
    letter = _letter(
        REAL_WORK,
        MIDDLE + " I would love to delve into the ever-evolving data platform space with you.",
        CLOSE,
    )
    result = review(letter, POSTING, example_profile)
    check = _check(result, "no phrases that read as machine-written")

    assert not check.ok
    assert not check.blocking
    assert result.ok  # advisory alone never forces a retry
    assert "delve" in check.detail


def test_flattery_is_advisory(example_profile):
    letter = _letter(
        REAL_WORK, MIDDLE + " Northwind is an industry leader and I have long admired it.", CLOSE
    )
    check = _check(review(letter, POSTING, example_profile), "no praise aimed at the employer")
    assert not check.ok and not check.blocking


def test_every_paragraph_opening_on_i_is_noticed(example_profile):
    letter = _letter(
        "I rewrote a nightly ingestion job as an asyncio worker pool, cutting it from 51 "
        "minutes to 9.",
        "I added contract tests around the 14 upstream PostgreSQL feeds and caught 3 schema "
        "changes.",
        "I maintain tidepool, which packs 40 years of NOAA constants into a 6 MB SQLite file.",
    )
    check = _check(review(letter, POSTING, example_profile), "varies how the paragraphs open")
    assert not check.ok and not check.blocking


def test_quoting_the_advert_back_is_noticed(example_profile):
    """Only whole sentences of it. A short requirement like "Production Python" is a phrase
    a truthful letter would use anyway, and flagging it would cost an iteration to relearn
    that the posting and the letter are about the same subject."""
    posting = POSTING.__class__(
        raw=POSTING.raw,
        title=POSTING.title,
        hard_skills=list(POSTING.hard_skills),
        keywords=list(POSTING.keywords),
        qualifications=["Comfortable owning a data ingestion path end to end in production"],
    )
    quoted = _letter(
        REAL_WORK,
        MIDDLE + " Comfortable owning a data ingestion path end to end in production.",
        CLOSE,
    )
    assert not _check(review(quoted, posting, example_profile), "does not restate the advert").ok
    assert _check(review(GOOD, posting, example_profile), "does not restate the advert").ok


# --------------------------------------------------------------- feedback ----


def test_feedback_leads_with_what_forced_the_retry(example_profile):
    letter = _letter("I am writing to apply for this role.", MIDDLE, CLOSE)
    text = feedback(review(letter, POSTING, example_profile))

    assert text.splitlines()[1].strip().startswith("- opens on something that happened")
    assert "most valuable one on the page" in text


def test_feedback_is_empty_when_there_is_nothing_to_say(example_profile):
    assert feedback(review(GOOD, POSTING, example_profile)) == ""
