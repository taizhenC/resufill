"""What can honestly be checked about a résumé's machine-readability — and what cannot.

Read this before adding a check.

Most published "ATS rules" are folklore. Several platforms *do* score a résumé now —
Greenhouse Talent Matching (2025), Lever Talent Fit (2025), Workday, Ashby, iCIMS — but each
scores against an employer's own calibration that nobody outside can see or reproduce, and
each documents the result as advisory input to a human. So a checker that claimed to predict
one would be lying.

What every one of them has in common is the *parser*, and that is the only place a formatting
decision has a demonstrable effect. So the rule for adding a check here is:

  it must be about something a parser or a human reviewer demonstrably does with the
  document, not about a number somebody claims a machine assigns to it.

Which splits the list in two, and the split is the point:

  PARSING   — the document is machine-readable at all. A bullet that is not in the PDF's
              text layer, or a job with no extractable dates, is invisible on the other
              side no matter how good it is. verify.py already proves the text layer
              round-trips; these checks cover the structure around it.

  READING   — the document is worth a human's six seconds. Quantified outcomes, verbs at
              the front, no "responsible for". These are advisory: they never fail a build,
              because a résumé that is 30% quantified is not broken, it is just weaker. They
              are fed back into the rewrite loop, which is the one place they can actually
              be acted on.

The evidence behind every check, and the reasoning for each thing left out, is in
docs/research/ats-and-cover-letters.md — including a check-by-check cross-reference of this
module against what its sources actually say.

Deliberately absent, because there is no evidence for them and the tool would be lying by
implication if it checked them: keyword density targets, "ATS match score" percentages,
white-text keyword injection (which is fraud, and detected), résumé length rules stated as
absolutes, and any claim that a specific font or file name affects ranking.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .document import ResumeDoc
from .profile import Profile
from .textutil import normalize, numbers

# The section names parsers are trained on. A parser files content under the heading above
# it; a heading it does not recognise sends that content to "other", where it carries no
# structured weight. render.SECTION_TITLES already emits from this set — the check exists
# because TEMPLATES_DIR lets a user replace the template and quietly leave it.
STANDARD_HEADINGS = frozenset({
    "summary", "professional summary", "profile", "objective",
    "skills", "technical skills", "core skills",
    "experience", "work experience", "professional experience", "employment history",
    "projects", "personal projects", "technical projects",
    "education", "certifications", "licenses", "certifications and licenses",
    "publications", "awards", "volunteer experience",
})

# "June 2025 – August 2025", "June 2025 – Present". Unambiguous to a parser: a spelled-out
# month, a four-digit year, and a range separator. What fails this is what a parser also
# fails on — "Summer 2024" (no month), "'23" (no century), "Ongoing" (not a date).
#
# Spelled out, because the abbreviations are not equally safe. OpenResume matches a month by
# `text.includes(month) || text.includes(month[:4])`, so "May", "June", "July" and "Sept"
# survive being shortened and "Jan", "Feb", "Mar", "Apr", "Aug", "Oct", "Nov" and "Dec" match
# nothing. profile.format_month writes the full name; this is the assertion that a
# hand-written date in profile.yaml did too.
_MONTH = (
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
)
DATE_RANGE = re.compile(
    rf"^{_MONTH}\s+\d{{4}}\s*[-–—]\s*(?:{_MONTH}\s+\d{{4}}|Present)$|^(?:{_MONTH}\s+\d{{4}}|Present)$"
)

# Openings that spend the most valuable words on the page saying nothing. A bullet's first
# two words are the ones a six-second scan reads; "Responsible for" describes a job
# description rather than anything the person did.
WEAK_OPENERS = re.compile(
    r"^\s*(?:responsible for|tasked with|duties included|helped (?:with|to)|assisted (?:with|in)|"
    r"worked (?:on|with)|involved in|participated in|in charge of|my role|part of a team)\b",
    re.I,
)

# A résumé is written in an implied first person; making it explicit costs words and reads
# as a cover letter. This is one of the few pieces of guidance every university career
# office states the same way.
FIRST_PERSON = re.compile(r"(?<![a-z])(?:i|me|my|mine|myself|we|our|us)(?![a-z])", re.I)

# Two rendered lines at 10.5pt on a Letter page with 0.5in margins. Past this a bullet wraps
# to a third line and stops being scannable, which is the only thing a bullet is for.
MAX_BULLET_CHARS = 240
# A HOUSE CONVENTION, and labelled as one on purpose.
#
# Every university career office and every study says "quantify where you can". Not one of
# them specifies a fraction, and a search for a source for any particular ratio comes back
# empty — so this number is a choice, not a finding, and the check that reads it is advisory
# for exactly that reason. It is the share at which the *unquantified* bullets start looking
# like the exception rather than the rule, which is a judgement, and it is stated as one
# wherever the user sees it.
MIN_QUANTIFIED = 0.4


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    # "parsing" failures make the document unreadable to a machine; "reading" failures make
    # it weaker to a person. Only the first kind is ever allowed to fail a build.
    kind: str = "parsing"
    # What to do about it, in the second person, because a check that only says "no" makes
    # the reader guess.
    fix: str = ""

    @property
    def blocking(self) -> bool:
        return self.kind == "parsing"


@dataclass
class AtsReport:
    checks: list[Check] = field(default_factory=list)

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]

    @property
    def parsing_failures(self) -> list[Check]:
        return [c for c in self.failed if c.blocking]

    @property
    def reading_failures(self) -> list[Check]:
        return [c for c in self.failed if not c.blocking]

    @property
    def ok(self) -> bool:
        """Machine-readable. Advisory failures deliberately do not count: a résumé that is
        30% quantified is weaker, not broken, and failing a build over it would make the
        tool's one real guarantee mean less by association."""
        return not self.parsing_failures

    @property
    def ratio(self) -> float:
        return (sum(1 for c in self.checks if c.ok) / len(self.checks)) if self.checks else 1.0

    def summary(self) -> str:
        passed = sum(1 for c in self.checks if c.ok)
        line = f"{passed} of {len(self.checks)} ATS checks passed"
        if self.parsing_failures:
            line += f"; {len(self.parsing_failures)} would affect parsing"
        return line

    def as_dict(self) -> list[dict]:
        return [
            {"name": c.name, "ok": c.ok, "detail": c.detail, "kind": c.kind, "fix": c.fix}
            for c in self.checks
        ]


# ------------------------------------------------------------------ checks ----


def _bullets(doc: ResumeDoc) -> list[str]:
    return [b.text for _, b in doc.bullets()]


def _entries(doc: ResumeDoc, profile: Profile):
    """The profile entries the document selected, with the section they were printed under.

    Facts come from the profile, never from the document — same rule as the renderer, for
    the same reason: a date the model wrote is a date that can be wrong.
    """
    by_id = {
        "experience": {e.id: e for e in profile.experience},
        "projects": {p.id: p for p in profile.projects},
        "education": {e.id: e for e in profile.education},
    }
    for section, entries in doc.entry_groups():
        for entry in entries:
            source = by_id[section].get(entry.source_id)
            if source is not None:
                yield section, source


def check_headings(doc: ResumeDoc) -> Check:
    from .render import SECTION_TITLES

    titles = [SECTION_TITLES[name] for name in doc.ordered_sections()]
    unknown = [t for t in titles if normalize(t) not in STANDARD_HEADINGS]
    return Check(
        "standard section headings",
        not unknown,
        "every heading is one a parser is trained on" if not unknown
        else f"a parser will file these under 'other': {', '.join(unknown)}",
        fix="Use the conventional wording — Experience, Education, Skills, Projects.",
    )


def check_dates(doc: ResumeDoc, profile: Profile) -> Check:
    bad = [
        f"{source.label}: {source.dates!r}"
        for _, source in _entries(doc, profile)
        if source.dates and not DATE_RANGE.match(source.dates)
    ]
    return Check(
        "parseable dates",
        not bad,
        "every entry's dates are month-and-year" if not bad
        else f"{len(bad)} entr(y/ies) a parser cannot read as a date: {'; '.join(bad[:3])}",
        fix="Write start/end in profile.yaml as YYYY-MM and this formats itself. 'Summer 2024' "
            "and \"'23\" have no month or no century, and a parser drops the whole range rather "
            "than guessing; a shortened month name ('Aug 2025') matches nothing in at least one "
            "real parser's month table.",
    )


def check_contact(profile: Profile) -> list[Check]:
    """Split, because the two halves fail differently.

    Email is what a parser keys the candidate record on — without it there is a résumé and
    no way to attach it to a person, which is the one contact failure that is not merely
    untidy. Phone and location are fields the record will simply have empty, and a recruiter
    filtering on location will not find you; that is worth saying and not worth failing on.
    """
    optional = [
        label for label, value in
        (("phone", profile.basics.phone), ("location", profile.basics.location))
        if not value
    ]
    return [
        Check(
            "email address present",
            bool(profile.basics.email),
            "present" if profile.basics.email else "no email — the parsed record has no key",
            fix="Set basics.email in profile.yaml.",
        ),
        Check(
            "phone and location present",
            not optional,
            "both present" if not optional else f"the parsed record will have no {', '.join(optional)}",
            kind="reading",
            fix="Set these in profile.yaml. Recruiters filter on location, and an empty "
                "field does not match a filter.",
        ),
    ]


def check_single_column(html: str) -> Check:
    """The layout rule everything else rests on.

    Measured, not assumed — see the header of resume.css. Rendering a two-column entry
    header and extracting the text puts the right-hand column *after* the bullets, so every
    date in the document lands together at the end of the text layer, detached from the job
    it describes. The renderer produces one column; this exists because TEMPLATES_DIR lets a
    user replace the template.
    """
    found = [
        name for name, pattern in (
            ("a table", r"<table\b"),
            ("a flex container", r"display\s*:\s*(?:inline-)?flex"),
            ("a grid container", r"display\s*:\s*(?:inline-)?grid"),
            ("a float", r"float\s*:\s*(?:left|right)"),
            ("absolute positioning", r"position\s*:\s*absolute"),
            ("an image", r"<img\b|<svg\b"),
            ("a multi-column rule", r"column-count\s*:"),
        )
        if re.search(pattern, html, re.I)
    ]
    return Check(
        "single column, no tables or images",
        not found,
        "one column of running text" if not found
        else f"the template uses {', '.join(found)}, which reorders or drops text on extraction",
        fix="Keep the résumé template to running text in one column. See the header of "
            "resume.css for what was measured.",
    )


def check_bullet_length(doc: ResumeDoc) -> Check:
    long = [b for b in _bullets(doc) if len(b) > MAX_BULLET_CHARS]
    return Check(
        "bullets fit two lines",
        not long,
        "no bullet runs past two lines" if not long
        else f"{len(long)} bullet(s) run to a third line",
        kind="reading",
        fix=f"Cut to about {MAX_BULLET_CHARS} characters. A bullet that wraps three times "
            "stops being scannable, which is the only thing a bullet is for.",
    )


def check_quantified(doc: ResumeDoc) -> Check:
    bullets = _bullets(doc)
    if not bullets:
        return Check("bullets carry numbers", True, "no bullets to check", kind="reading")
    with_numbers = [b for b in bullets if numbers(b)]
    share = len(with_numbers) / len(bullets)
    return Check(
        "bullets carry numbers",
        share >= MIN_QUANTIFIED,
        f"{len(with_numbers)} of {len(bullets)} bullets state a figure ({share:.0%})",
        kind="reading",
        fix="Prefer the recorded highlights that have numbers in them. The gate will not let "
            "a figure be invented, so this is a selection problem, not a writing one — and if "
            "the record has no numbers anywhere, that is the thing to go and fix. The "
            f"{MIN_QUANTIFIED:.0%} bar is this tool's convention, not a published finding: the "
            "advice everyone actually gives is \"quantify where you can\".",
    )


def check_openers(doc: ResumeDoc) -> Check:
    weak = [b for b in _bullets(doc) if WEAK_OPENERS.match(b)]
    return Check(
        "bullets lead with what was done",
        not weak,
        "every bullet opens on an action" if not weak
        else f"{len(weak)} bullet(s) open on filler: {'; '.join(b[:40] for b in weak[:3])}",
        kind="reading",
        fix="Start with the verb. 'Responsible for the ingestion pipeline' describes a job "
            "advert; 'Rewrote the ingestion pipeline' describes a person.",
    )


def check_first_person(doc: ResumeDoc) -> Check:
    found = [b for b in _bullets(doc) if FIRST_PERSON.search(b)]
    return Check(
        "no first-person pronouns",
        not found,
        "written in the implied first person" if not found
        else f"{len(found)} bullet(s) use I/my/we",
        kind="reading",
        fix="Drop the pronoun. A résumé is already in the first person; saying so spends "
            "words and reads like a cover letter.",
    )


def check_sections(doc: ResumeDoc) -> Check:
    have_history = bool(doc.experience or doc.projects)
    return Check(
        "has a work history section",
        have_history,
        "experience or projects present" if have_history
        else "nothing for a parser to read as employment history",
        fix="Select at least one experience or project entry.",
    )


def review(
    doc: ResumeDoc, profile: Profile, *, html: str = "", page_count: int | None = None,
    max_pages: int = 1,
) -> AtsReport:
    """Every check, in one report. `html` is optional so this can run before rendering."""
    checks = [
        check_sections(doc),
        check_headings(doc),
        check_dates(doc, profile),
        *check_contact(profile),
        check_bullet_length(doc),
        check_quantified(doc),
        check_openers(doc),
        check_first_person(doc),
    ]
    if html:
        checks.append(check_single_column(html))
    if page_count is not None:
        fits = page_count <= max_pages
        checks.append(
            Check(
                "fits the page budget", fits,
                f"{page_count} page(s), budget is {max_pages}",
                fix="Drop an entry or a bullet. Shrinking the font below about 9.5pt is a "
                    "worse outcome than a second page.",
            )
        )
    return AtsReport(checks=checks)


# ------------------------------------------------------------------ prompt ----

# Given to the tailor up front rather than only fed back after a failed check. The loop can
# fix these on a retry, but a retry is a model call — and every one of these is something
# the first draft could simply have done.
TAILOR_RULES = """10. Lead every bullet with the verb for what was done, never with "Responsible for",
   "Worked on" or "Helped with" — those describe a job advert rather than a person.
11. Prefer the recorded highlights that contain figures. Roughly half the bullets should
   state one. You may not invent or round a number, so this is a matter of which highlights
   you select, not of what you write.
12. No first-person pronouns. A résumé is already in the first person."""


def feedback(report: AtsReport) -> str:
    """What the tailor is told about the shape of the document, as opposed to its claims."""
    failures = report.reading_failures + report.parsing_failures
    if not failures:
        return ""
    lines = ["The draft is truthful but reads poorly for this format. Fix these:"]
    for check in failures:
        lines.append(f"  - {check.name}: {check.detail}")
        if check.fix:
            lines.append(f"    {check.fix}")
    return "\n".join(lines)
