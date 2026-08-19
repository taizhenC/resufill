"""The round trip: read the text back out of the PDF that was just produced, and fail the
build if it did not survive.

This is the guarantee that actually matters (PLAN.md §2). Several ATS platforms now do score
a résumé — Greenhouse Talent Matching, Lever Talent Fit, Workday, Ashby, iCIMS — but every
one of those scores is computed from an employer's own calibration that the candidate cannot
see, and nothing reproduces them, so the number in report.md remains an explicitly-labelled
local proxy.

What is *not* a proxy is whether the document parses. Every one of those systems, and every
recruiter search behind them, runs on what their parser extracted: if a bullet is not in the
text layer, no system on the other side will ever see it, and the résumé silently loses
whatever it said.

A PDF's text layer is not its markup, which is why this cannot be checked against the HTML:
a two-column header reorders, a webfont can fail to embed, a ligature can arrive as a glyph
with no Unicode mapping. So the assertion is made against the actual bytes that get sent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .document import CoverLetter, ResumeDoc
from .profile import Profile
from .textutil import normalize, truncate

# pdfminer emits a soft hyphen and a line break where Chromium hyphenated a word; both
# have to come out before comparing, or every wrapped bullet reads as missing.
_JOIN_HYPHEN = re.compile(r"[-­]\s*\n\s*")


@dataclass
class VerifyReport:
    ok: bool
    page_count: int
    missing: list[str] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=dict)
    text: str = ""

    def summary(self) -> str:
        if self.ok:
            return f"PDF parses: {self.page_count} page(s), every heading and bullet survived"
        return f"PDF round-trip FAILED: {len(self.missing)} item(s) did not survive extraction"


def extract_text(pdf_path: Path) -> str:
    from pdfminer.high_level import extract_text as _extract

    return _extract(str(pdf_path)) or ""


def flatten(text: str) -> str:
    """Normalised, de-hyphenated, single-line. A bullet wraps across two or three lines in
    the PDF and has to be found as one string."""
    return normalize(_JOIN_HYPHEN.sub("", text or "").replace("\n", " "))


def verify(
    pdf_path: Path,
    doc: ResumeDoc,
    profile: Profile,
    *,
    max_pages: int = 1,
    page_count: int | None = None,
) -> VerifyReport:
    """Every claim the build makes about its own output, checked against the output."""
    raw = extract_text(pdf_path)
    haystack = flatten(raw)
    missing: list[str] = []
    checks: dict[str, bool] = {}

    def require(label: str, needle: str, *, quote: str = "") -> None:
        present = bool(needle) and flatten(needle) in haystack
        checks[label] = present
        if not present:
            missing.append(f"{label}: {truncate(quote or needle, 80)}")

    require("name", profile.basics.name)
    if profile.basics.email:
        require("email", profile.basics.email)
    if profile.basics.phone:
        # Chromium can break a phone number across a line; compare on digits alone.
        digits = re.sub(r"\D", "", profile.basics.phone)
        present = digits in re.sub(r"\D", "", raw)
        checks["phone"] = present
        if not present:
            missing.append(f"phone: {profile.basics.phone}")

    for section in _expected_headings(doc, profile):
        require(f"heading:{section}", section)

    for where, bullet in doc.bullets():
        require(f"bullet:{where}", bullet.text, quote=bullet.text)
    if doc.summary.strip():
        require("summary", doc.summary)

    pages = page_count if page_count is not None else _count_pages(pdf_path)
    fits = pages <= max_pages
    checks["page_budget"] = fits
    if not fits:
        missing.append(f"length: {pages} pages, budget is {max_pages}")

    return VerifyReport(
        ok=not missing, page_count=pages, missing=missing, checks=checks, text=raw
    )


def verify_letter(
    pdf_path: Path,
    letter: CoverLetter,
    profile: Profile,
    *,
    max_pages: int = 1,
    page_count: int | None = None,
) -> VerifyReport:
    """The same round trip for the letter. A cover letter is more often pasted into a
    textarea than parsed by an ATS, which makes clean extraction matter more, not less."""
    raw = extract_text(pdf_path)
    haystack = flatten(raw)
    missing: list[str] = []
    checks: dict[str, bool] = {}

    for label, needle in [("name", profile.basics.name), ("addressee", letter.addressee)]:
        checks[label] = bool(needle) and flatten(needle) in haystack
        if needle and not checks[label]:
            missing.append(f"{label}: {needle}")

    for where, paragraph in letter.cited():
        present = flatten(paragraph.text) in haystack
        checks[f"paragraph:{where}"] = present
        if not present:
            missing.append(f"{where}: {truncate(paragraph.text, 80)}")

    pages = page_count if page_count is not None else _count_pages(pdf_path)
    checks["page_budget"] = pages <= max_pages
    if not checks["page_budget"]:
        missing.append(f"length: {pages} pages, budget is {max_pages}")

    return VerifyReport(ok=not missing, page_count=pages, missing=missing, checks=checks, text=raw)


def _expected_headings(doc: ResumeDoc, profile: Profile) -> list[str]:
    """Only the headings the document actually renders. Asserting a heading that was never
    emitted would fail every build that legitimately has no projects."""
    from .render import SECTION_TITLES

    present = []
    for name in doc.ordered_sections():
        has_content = {
            "summary": bool(doc.summary.strip()),
            "skills": any(doc.skills.values()),
            "experience": bool(doc.experience),
            "projects": bool(doc.projects),
            "education": bool(doc.education),
            "certifications": bool(doc.certification_ids and profile.certifications),
        }[name]
        if has_content:
            present.append(SECTION_TITLES[name])
    return present


def _count_pages(pdf_path: Path) -> int:
    from .render import page_count

    return page_count(pdf_path)
