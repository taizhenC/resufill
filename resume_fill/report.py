"""`report.md` — what the run actually concluded.

The score is printed as a breakdown, never as a bare number, because a bare number invites
exactly the misreading PLAN.md §2 warns about: no employer computes it. The part worth
reading is the gap list, split into the two kinds that mean different things — a keyword
that is in your record but did not get surfaced is a tailoring miss, and a keyword that is
nowhere in your record is a fact about you.
"""

from __future__ import annotations

from datetime import date

from .document import ResumeDoc
from .ground import Violation
from .jd import JobDescription
from .profile import Profile
from .score import Ceiling, Score
from .source import SourceIndex
from .verify import VerifyReport


def _table(score: Score) -> list[str]:
    rows = [
        "| Component | Weight | Score | Points | Why |",
        "|---|---:|---:|---:|---|",
    ]
    for component in score.components:
        rows.append(
            f"| {component.label} | {component.weight:.2f} | {component.raw:.0%} | "
            f"{component.points:.1f} | {component.detail} |"
        )
    rows.append(f"| **Total** | | | **{score.total:.1f}** | |")
    return rows


def _ceiling_note(score: Score, ceiling: Ceiling | None, threshold: float) -> list[str]:
    """What the threshold means for *this* record and *this* posting.

    Printing "62.4 against a threshold of 80" reads as a failure. Very often it is not one:
    the posting asked for things the record has never contained, ground.py made sure no
    rewrite could invent them, and 64.1 was the highest number available before the first
    word was written. That is worth saying in the same breath as the score, not three
    sections later in the gap list.
    """
    if ceiling is None:
        return []
    if ceiling.is_reachable(threshold):
        if score.total >= threshold:
            return []
        return [
            f"The threshold of {threshold:.0f} was reachable for this record — this posting caps at "
            f"{ceiling.total:.1f} and the draft got {score.total:.1f}. The shortfall is tailoring, "
            "not the record: see the unsurfaced keywords below.",
            "",
        ]
    lines = [
        f"**The threshold of {threshold:.0f} was never reachable here.** The highest score this "
        f"record can get against this posting is {ceiling.total:.1f}, because the posting asks for "
        "things nothing in it supports and the grounding gate will not let them be invented. A low "
        "ceiling is the answer to the question, not a failure to answer it.",
        "",
    ]
    if ceiling.unreachable:
        lines += [
            "Out of reach for this record: " + ", ".join(ceiling.unreachable[:15]),
            "",
        ]
    return lines


def _citations(doc: ResumeDoc, index: SourceIndex) -> list[str]:
    """Every bullet with the source it came from.

    This is the receipt. supports_number() accepts a figure whose *unit* differs from the
    source's wording, which is a deliberate trade — so the source sits next to the claim
    where it can be checked by eye.
    """
    lines = []
    for where, bullet in doc.bullets():
        labels = [index[sid].label for sid in bullet.source_ids if sid in index]
        lines.append(f"- **{where}** — {bullet.text}")
        lines.append(f"  - source: {'; '.join(labels) or '(none)'}")
    return lines


def build(
    *,
    doc: ResumeDoc,
    profile: Profile,
    jd: JobDescription,
    score: Score,
    index: SourceIndex,
    verify_report: VerifyReport | None,
    iterations: int,
    threshold: float,
    blocked_terms: list[str],
    violations: list[Violation],
    removed: list[str] | None = None,
    ceiling: Ceiling | None = None,
    stop_reason: str = "",
) -> str:
    headline = f"**{score.total:.1f} / 100** (threshold {threshold:.0f})"
    if ceiling is not None:
        headline = (
            f"**{score.total:.1f}** of a reachable **{ceiling.total:.1f}** "
            f"(threshold {threshold:.0f})"
        )
    lines: list[str] = [
        f"# {jd.title or 'Untitled role'} — {jd.company or 'unknown company'}",
        "",
        f"Generated {date.today().isoformat()} by resume-fill. Iterations: {iterations}"
        + (f", stopped because {stop_reason}." if stop_reason else "."),
        "",
        "## Score",
        "",
        headline,
        "",
        "> This number is a **local proxy**. No employer computes it: Greenhouse and Lever do not",
        "> rank by keyword at all, and Taleo/iCIMS keyword search happens recruiter-side. Treat it",
        "> as a stopping rule for the rewrite loop, not as a prediction.",
        "",
        *_table(score),
        "",
        *_ceiling_note(score, ceiling, threshold),
    ]

    if verify_report is not None:
        lines += ["## Parse check", "", f"{verify_report.summary()}", ""]
        if verify_report.missing:
            lines += ["Did not survive extraction:", ""]
            lines += [f"- {item}" for item in verify_report.missing]
            lines.append("")

    real, unsurfaced = score.real_gaps(), score.unsurfaced()
    lines += ["## Gaps", ""]
    if real:
        lines += [
            "### Not in your record at all",
            "",
            "The posting asks for these and nothing in `profile.yaml` or the evidence corpus",
            "supports them. They were deliberately left out — this is the honest reading of the",
            "score's ceiling, and the list is what the role would need you to go and do.",
            "",
        ]
        lines += [f"- {gap.keyword}" for gap in real]
        lines.append("")
    if unsurfaced:
        lines += [
            "### In your record, but not on this résumé",
            "",
            "These you have. They did not make the cut for this posting — either the loop ran out",
            "of iterations or the page budget did. Worth a look.",
            "",
        ]
        lines += [f"- {gap.keyword} — recorded in: {gap.where}" for gap in unsurfaced]
        lines.append("")
    if not real and not unsurfaced:
        lines += ["Every keyword the posting named appears on the résumé.", ""]

    if score.matched:
        lines += ["## Matched", "", ", ".join(score.matched), ""]

    if score.unaddressed_qualifications:
        lines += [
            "## Qualifications the résumé does not answer",
            "",
            *[f"- {q}" for q in score.unaddressed_qualifications],
            "",
        ]

    if removed:
        lines += [
            "## Removed so the rest could be kept",
            "",
            "The draft claimed these and the record could not back them, so they were cut and the",
            "remainder was put back through the same gate. This résumé is therefore shorter than",
            "the one the model wrote — which is the trade, and it is stated here rather than",
            "absorbed silently.",
            "",
            *[f"- {item}" for item in removed],
            "",
        ]

    if blocked_terms:
        lines += [
            "## Blocked by the grounding gate",
            "",
            "The tailor tried to claim these and could not support them from the record. They were",
            "removed rather than rephrased. If any of them is genuinely true of you, that is a hole",
            "in `profile.yaml`, not in the résumé.",
            "",
            *[f"- {term}" for term in blocked_terms],
            "",
        ]

    if violations:
        lines += [
            "## Unresolved grounding violations",
            "",
            "The loop ended with these outstanding. The PDF was not written.",
            "",
            *[f"- [{v.kind}] {v}" for v in violations],
            "",
        ]

    lines += ["## Citations", "", *_citations(doc, index), ""]
    return "\n".join(lines)


def cover_section(cover_run, jd: JobDescription, index: SourceIndex) -> str:
    """The cover letter's half of report.md.

    Shorter than the résumé's because there is no score: inventing one for a letter would
    be inventing a metric, and the résumé's proxy is already labelled as a proxy. What is
    worth printing is the same thing that matters for the résumé — what each paragraph is
    standing on.
    """
    best = cover_run.best
    letter = best.document
    lines = [
        "",
        f"# Cover letter — {jd.company or 'unknown company'}",
        "",
        f"Addressed to: {letter.addressee or '(unset)'} · {letter.word_count()} words · "
        f"{len(letter.paragraphs)} paragraph(s) · {len(cover_run.attempts)} iteration(s)",
        "",
    ]
    if best.verify_report is not None:
        lines += [best.verify_report.summary(), ""]
        if best.verify_report.missing:
            lines += [f"- {item}" for item in best.verify_report.missing] + [""]
    if best.repair is not None and best.repair.dropped:
        lines += [
            "## Removed so the rest could be kept",
            "",
            *[f"- {v.where} — {v.detail}" for v in best.repair.dropped],
            "",
        ]
    if best.violations:
        lines += [
            "## Unresolved grounding violations",
            "",
            "The loop ended with these outstanding. No cover letter PDF was written.",
            "",
            *[f"- [{v.kind}] {v}" for v in best.violations],
            "",
        ]
    if cover_run.blocked_terms:
        lines += [
            "## Blocked by the grounding gate",
            "",
            *[f"- {term}" for term in cover_run.blocked_terms],
            "",
        ]
    lines += ["## Citations", ""]
    for where, paragraph in letter.cited():
        labels = [index[sid].label for sid in paragraph.source_ids if sid in index]
        lines.append(f"- **{where}** — {paragraph.text}")
        lines.append(f"  - source: {'; '.join(labels) or '(none)'}")
    lines.append("")
    return "\n".join(lines)
