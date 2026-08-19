"""Salvaging a rejected draft instead of throwing the iteration away.

The gate is unchanged and these tests exist to prove it: everything here is removal. What
comes back has been through `check()` a second time, so a repaired document is grounded in
exactly the sense the un-repaired one was supposed to be — it is simply smaller.

The thing being fixed is the *cost* of a rejection. One bad token used to cost fifteen good
bullets and a whole iteration, and with MAX_ITER at 4, three unlucky drafts produced no
document at all.
"""

from resume_fill.document import Bullet, CoverLetter, Paragraph, ResumeDoc, SelectedEntry
from resume_fill.ground import check, check_letter, repair, repair_letter

GOOD = (
    "Rewrote the nightly ingestion job as an asyncio worker pool, cutting the run from 51 "
    "minutes to 9.",
    ["exp-northwind-backend.h1"],
)
ALSO_GOOD = (
    "Added contract tests around the 14 upstream feeds, catching 3 silent schema changes.",
    ["exp-northwind-backend.h2"],
)
INVENTED_NUMBER = ("Cut nightly ingestion time by 94%.", ["exp-northwind-backend.h1"])
INVENTED_TOOL = ("Ran the ingestion pool on Kubernetes.", ["exp-northwind-backend.h1"])


def _doc(*bullets, **kwargs) -> ResumeDoc:
    return ResumeDoc(
        experience=[
            SelectedEntry(
                source_id="exp-northwind-backend",
                bullets=[Bullet(text=t, source_ids=s) for t, s in bullets],
            )
        ],
        **kwargs,
    )


def _repair(doc, profile):
    index = profile.sources()
    return repair(doc, profile, index, check(doc, profile, index))


def test_one_bad_bullet_costs_one_bullet_not_the_document(example_profile):
    doc = _doc(GOOD, INVENTED_NUMBER, ALSO_GOOD)
    result = _repair(doc, example_profile)

    assert result.ok
    kept = [b.text for _, b in result.doc.bullets()]
    assert kept == [GOOD[0], ALSO_GOOD[0]]
    assert len(result.dropped) == 1
    assert result.dropped[0].kind == "unsupported_number"


def test_the_repaired_document_passes_the_same_gate_that_rejected_it(example_profile):
    """This is the whole claim. Repair is removal, so what comes back is grounded — not
    grounded-ish, not grounded-with-a-warning."""
    doc = _doc(GOOD, INVENTED_TOOL)
    result = _repair(doc, example_profile)

    assert result.remaining == []
    assert check(result.doc, example_profile, example_profile.sources()) == []


def test_repair_never_rewrites_a_bullet_it_keeps(example_profile):
    doc = _doc(GOOD, INVENTED_TOOL)
    result = _repair(doc, example_profile)

    assert [b.text for _, b in result.doc.bullets()] == [GOOD[0]]
    assert result.doc.experience[0].bullets[0].source_ids == list(GOOD[1])


def test_a_draft_that_is_wrong_all_the_way_through_is_still_a_rejection(example_profile):
    """Repairing to nothing is not a result. An empty résumé is a failed run wearing a PDF,
    and the loop has to retry rather than render it."""
    doc = _doc(INVENTED_NUMBER, INVENTED_TOOL)
    result = _repair(doc, example_profile)

    assert not result.ok
    assert result.doc.is_empty()


def test_an_entry_stripped_of_every_bullet_goes_with_them(example_profile):
    """A company name and a date with nothing under it is not an entry."""
    doc = ResumeDoc(
        experience=[
            SelectedEntry(
                source_id="exp-northwind-backend",
                bullets=[Bullet(text=GOOD[0], source_ids=list(GOOD[1]))],
            ),
            SelectedEntry(
                source_id="exp-campus-it",
                bullets=[Bullet(text=INVENTED_TOOL[0], source_ids=["exp-campus-it.h1"])],
            ),
        ]
    )
    result = _repair(doc, example_profile)

    assert result.ok
    assert [e.source_id for e in result.doc.experience] == ["exp-northwind-backend"]


def test_an_entry_the_catalogue_does_not_have_is_removed_with_its_bullets(example_profile):
    doc = ResumeDoc(
        experience=[
            SelectedEntry(
                source_id="exp-northwind-backend",
                bullets=[Bullet(text=GOOD[0], source_ids=list(GOOD[1]))],
            ),
            SelectedEntry(
                source_id="exp-invented-startup",
                bullets=[Bullet(text="Founded a company.", source_ids=["exp-invented-startup.h1"])],
            ),
        ]
    )
    result = _repair(doc, example_profile)

    assert result.ok
    assert [e.source_id for e in result.doc.experience] == ["exp-northwind-backend"]


def test_an_undeclared_skill_is_removed_from_the_block_it_sat_in(example_profile):
    doc = _doc(GOOD, skills={"Languages": ["Python", "Haskell"], "Data": ["PostgreSQL"]})
    result = _repair(doc, example_profile)

    assert result.ok
    assert result.doc.skills == {"Languages": ["Python"], "Data": ["PostgreSQL"]}


def test_a_skills_category_emptied_by_repair_does_not_render_as_a_bare_heading(example_profile):
    doc = _doc(GOOD, skills={"Languages": ["Python"], "Invented": ["Haskell"]})
    result = _repair(doc, example_profile)

    assert result.ok
    assert result.doc.skills == {"Languages": ["Python"]}


def test_a_summary_that_claims_something_unsupported_is_cleared_not_edited(example_profile):
    doc = _doc(
        GOOD,
        summary="Backend engineer working in Kubernetes and Rust.",
        summary_source_ids=["exp-northwind-backend"],
    )
    result = _repair(doc, example_profile)

    assert result.ok
    assert result.doc.summary == ""
    assert result.doc.summary_source_ids == []


def test_a_certification_that_does_not_exist_is_dropped(example_profile):
    doc = _doc(GOOD, certification_ids=["cert-aws-cloud-practitioner", "cert-invented"])
    result = _repair(doc, example_profile)

    assert result.ok
    assert result.doc.certification_ids == ["cert-aws-cloud-practitioner"]


def test_repairing_a_clean_document_changes_nothing(example_profile):
    doc = _doc(GOOD, ALSO_GOOD)
    result = _repair(doc, example_profile)

    assert result.ok
    assert not result.changed
    assert result.summary() == "nothing to repair"
    assert result.doc.model_dump() == doc.model_dump()


def test_the_summary_names_what_was_cut(example_profile):
    doc = _doc(GOOD, INVENTED_NUMBER, INVENTED_TOOL)
    result = _repair(doc, example_profile)

    assert result.summary() == "unsupported_numberx1, unsupported_termx1"
    assert len(result.notes()) == 2


# ------------------------------------------------------------ cover letter ----


def _letter(*paragraphs: tuple[str, list[str]]) -> CoverLetter:
    return CoverLetter(
        addressee="Hiring Manager",
        paragraphs=[Paragraph(text=t, source_ids=s) for t, s in paragraphs],
    )


P1 = (
    "I rewrote a nightly ingestion job as an asyncio worker pool and cut the run from 51 "
    "minutes to 9.",
    ["exp-northwind-backend.h1"],
)
P2 = (
    "I put contract tests around the 14 upstream feeds, which caught 3 silent schema changes.",
    ["exp-northwind-backend.h2"],
)
P3 = (
    "I maintain tidepool, which packs 40 years of NOAA harmonic constants into a 6 MB SQLite file.",
    ["proj-tidepool.h1"],
)
P_BAD = ("I have run production Kubernetes clusters for three years.", ["exp-northwind-backend.h1"])


def test_a_letter_survives_losing_one_paragraph(example_profile):
    letter = _letter(P1, P2, P_BAD, P3)
    index = example_profile.sources()
    result = repair_letter(
        letter, example_profile, index, check_letter(letter, example_profile, index)
    )

    assert result.ok
    assert [p.text for p in result.letter.paragraphs] == [P1[0], P2[0], P3[0]]


def test_a_letter_cut_below_two_paragraphs_is_not_a_letter(example_profile):
    """Cutting a paragraph out of a short letter removes a quarter of it. Past a point the
    honest move is to write it again, not to ship the fragment."""
    letter = _letter(P1, P_BAD, P_BAD)
    index = example_profile.sources()
    result = repair_letter(
        letter, example_profile, index, check_letter(letter, example_profile, index)
    )

    assert not result.ok
    assert len(result.letter.paragraphs) == 1
