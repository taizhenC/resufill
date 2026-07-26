"""An existing résumé PDF -> profile.yaml seed.

The LinkedIn export gives the skeleton but rarely the bullets: most people never paste
their résumé bullets into LinkedIn descriptions. This reads them back out of the PDF
they *do* have, plus the contact block, which the export omits entirely.

Extraction from a PDF is heuristic and this module is honest about it: it returns what it
found plus a list of `notes` naming everything it had to guess, which `init` prints so the
guesses get corrected once, by hand, in the file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..profile import Basics, Education, Experience, Highlight, Link, Profile, Project
from .linkedin import IdMaker, parse_date

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}")
_PHONE = re.compile(r"(?:\+?\d{1,2}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}")
_URL = re.compile(r"(?:https?://)?(?:www\.)?(?:linkedin\.com/in/|github\.com/|[\w-]+\.[a-z]{2,})[\w./#-]*", re.I)
_BULLET = re.compile(r"^\s*[•‣▪·◦*–—\-]\s+")
# "Brooklyn, NY" / "New York, New York" / "Palo Alto, CA" — at most three words before the
# comma, so a name immediately preceding a city cannot be swallowed into the match.
_LOCATION = re.compile(
    r"[A-Z][A-Za-z.'\-]+(?: [A-Z][A-Za-z.'\-]+){0,2},\s*(?:[A-Z]{2}|[A-Z][a-z]+(?: [A-Z][a-z]+)?)"
)
_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*"
_DATE_RANGE = re.compile(
    rf"((?:{_MONTH}\.?\s+)?\d{{4}})\s*(?:[-–—]|to)\s*((?:{_MONTH}\.?\s+)?\d{{4}}|Present|Current|Now)",
    re.I,
)
_SINGLE_DATE = re.compile(rf"(?:{_MONTH}\.?\s+)?\d{{4}}", re.I)

# Section headings, normalised to letters only. The value is the bucket we file it under.
_HEADINGS = {
    "experience": "experience", "workexperience": "experience", "professionalexperience": "experience",
    "employment": "experience", "employmenthistory": "experience", "relevantexperience": "experience",
    "internships": "experience", "workhistory": "experience",
    "education": "education", "academics": "education",
    "projects": "projects", "technicalprojects": "projects", "personalprojects": "projects",
    "selectedprojects": "projects",
    "skills": "skills", "technicalskills": "skills", "skillsandtools": "skills",
    "toolsandtechnologies": "skills", "technologies": "skills",
    "summary": "summary", "objective": "summary", "profile": "summary", "about": "summary",
    "certifications": "certifications", "licensesandcertifications": "certifications",
    "awards": "awards", "honors": "awards", "honorsandawards": "awards",
    "leadership": "leadership", "activities": "leadership", "volunteer": "leadership",
    "publications": "publications", "coursework": "coursework", "relevantcoursework": "coursework",
    "interests": "interests", "languages": "languages",
}


@dataclass
class Block:
    """One entry inside a section: the header lines, then its bullets."""

    header: list[str] = field(default_factory=list)
    bullets: list[str] = field(default_factory=list)
    dates: tuple[str, str] = ("", "")


@dataclass
class Scrape:
    basics: Basics
    sections: dict[str, list[Block]]
    notes: list[str]


def extract_text(path: Path) -> str:
    from pdfminer.high_level import extract_text as _extract

    return _extract(str(path)) or ""


def _clean_lines(text: str) -> list[str]:
    out = []
    for raw in text.splitlines():
        line = raw.replace("\xa0", " ").rstrip()
        # pdfminer pads columns with runs of spaces; collapse them so a "Company … Dates"
        # line reads as one line rather than as two columns glued together.
        line = re.sub(r"\s{2,}", "  ", line).strip()
        if line:
            out.append(line)
    return out


def _heading_of(line: str) -> str | None:
    if len(line) > 44:
        return None
    key = re.sub(r"[^a-z]", "", line.casefold())
    return _HEADINGS.get(key)


def _parse_contact(lines: list[str]) -> tuple[Basics, list[str]]:
    """The contact block is whatever is above the first section heading."""
    notes: list[str] = []
    head: list[str] = []
    for line in lines:
        if _heading_of(line):
            break
        head.append(line)
    blob = " ".join(head)

    email = match.group(0) if (match := _EMAIL.search(blob)) else ""
    phone = match.group(0) if (match := _PHONE.search(blob)) else ""

    links = []
    for match in _URL.finditer(blob):
        url = match.group(0).rstrip(".,;)")
        if "@" in url or len(url) < 8:
            continue
        links.append(Link(label="", url=url if url.startswith("http") else f"https://{url}"))

    # The name is the first line that is not contact data. On a well-formed résumé it is
    # also the largest text on the page, but pdfminer discards size, so position it is.
    name = ""
    for line in head:
        if _EMAIL.search(line) or _PHONE.search(line) or line.count("|") >= 2:
            continue
        if 2 <= len(line) <= 60 and not line.startswith("http"):
            name = line.strip("|,- ")
            break
    if not name:
        notes.append("could not find a name in the PDF header - set basics.name by hand")

    # Split the contact block into fields before looking for a city: searching the joined
    # blob lets "Ada Lovelace Brooklyn, NY" match as one place name.
    fields = [f.strip() for line in head for f in re.split(r"\s*[|·•]\s*|\s{2,}", line) if f.strip()]
    location = next((f for f in fields if _LOCATION.fullmatch(f)), "")
    if not email:
        notes.append("no email found in the PDF - set basics.email by hand")

    return (
        Basics(name=name or "TODO your name", email=email, phone=phone, location=location, links=links),
        notes,
    )


# Entry headers are short; bullets are sentences. Measured against real résumés this is
# the single most reliable signal once the bullet glyph is gone — and it often is, because
# a PDF's list markers are drawn, not written into the text layer.
_LONG_LINE = 55


def classify(line: str, block: Block | None) -> str:
    """One of: bullet | header | continuation.

    Kept separate from the walk below because it is the whole heuristic, and the walk is
    just bookkeeping.
    """
    if _BULLET.match(line):
        return "bullet"
    dates = _DATE_RANGE.search(line)
    long_line = len(line) >= _LONG_LINE
    # A date range that *ends* the line is an entry header ("Acme | NY | Jun 2025 – Aug 2025").
    # A date range buried mid-sentence is prose ("grew revenue between 2023 – 2024 by ...").
    if dates and (not long_line or dates.end() >= len(line) - 2):
        return "header"
    if long_line and block is not None and (block.header or block.bullets):
        return "bullet"
    if block is not None and block.bullets and (line[:1].islower() or line[:1].isdigit()):
        return "continuation"
    return "header"


def _split_sections(lines: list[str]) -> dict[str, list[Block]]:
    """Walk the document once, filing every line under the heading above it.

    A Block is one entry: its header lines (company, title, dates, in whatever order the
    PDF happened to emit them) followed by its bullets. A new Block starts on a header line
    that follows bullets — i.e. the previous entry is finished.
    """
    sections: dict[str, list[Block]] = {}
    current: str | None = None
    block: Block | None = None

    for line in lines:
        heading = _heading_of(line)
        if heading:
            current, block = heading, None
            sections.setdefault(heading, [])
            continue
        if current is None:
            continue

        kind = classify(line, block)
        dates_here = _DATE_RANGE.search(line)
        # A line that is *only* a date range, arriving after the bullets, is the tell-tale
        # of a two-column entry header: the layout engine emits the right-hand column last.
        # (Verified: Chromium flexbox does exactly this, which is also why the résumé this
        # tool renders is single-column.) Attach it to the entry it belongs to rather than
        # opening a phantom one.
        orphan_dates = bool(
            dates_here
            and block is not None
            and not block.dates[0]
            and not _DATE_RANGE.sub("", line).strip(" |,-–—")
        )
        if block is None or (kind == "header" and block.bullets and not orphan_dates):
            block = Block()
            sections[current].append(block)

        if kind == "bullet":
            block.bullets.append(_BULLET.sub("", line).strip())
        elif kind == "continuation":
            block.bullets[-1] = f"{block.bullets[-1]} {line}".strip()
        else:
            dates = _DATE_RANGE.search(line)
            if dates and not block.dates[0]:
                block.dates = (parse_date(dates.group(1)), _end_date(dates.group(2)))
                line = _DATE_RANGE.sub("", line).strip(" |,-–—")
            if line:
                block.header.append(line)
    return sections


def _end_date(text: str) -> str:
    return "" if re.match(r"present|current|now", text.strip(), re.I) else parse_date(text)


def _company_and_title(header: list[str]) -> tuple[str, str, str]:
    """Guess (company, title, location) from an entry's header lines.

    Résumés put these in either order, so this returns a guess and `init` prints it for
    review rather than pretending to know.
    """
    parts: list[str] = []
    for line in header:
        parts.extend(p.strip() for p in re.split(r"\s{2,}|\s+[|·]\s+", line) if p.strip())
    location = ""
    for part in list(parts):
        if re.fullmatch(r"[A-Z][a-zA-Z.\s]+,\s*(?:[A-Z]{2}|[A-Z][a-z]+)", part) or part.lower() in {"remote"}:
            location, parts = part, [p for p in parts if p != part]
            break
    company = parts[0] if parts else ""
    title = parts[1] if len(parts) > 1 else ""
    # "Software Engineer Intern" in slot 0 and an employer in slot 1 is the other common
    # layout; a role word is the reliable tell.
    role_words = re.compile(r"engineer|developer|intern|analyst|scientist|manager|designer|researcher|assistant|lead", re.I)
    if title and role_words.search(company) and not role_words.search(title):
        company, title = title, company
    return company, title, location


def scrape(path: Path) -> Scrape:
    lines = _clean_lines(extract_text(path))
    if not lines:
        raise RuntimeError(
            f"{path} yielded no text - it is probably a scan. resume-fill needs a text PDF "
            "(the same property that makes a résumé ATS-parseable)."
        )
    basics, notes = _parse_contact(lines)
    return Scrape(basics=basics, sections=_split_sections(lines), notes=notes)


def to_profile(path: Path) -> tuple[Profile, list[str]]:
    """Best-effort Profile from a résumé PDF alone, for when there is no LinkedIn export."""
    result = scrape(path)
    ids, notes = IdMaker(), list(result.notes)

    experience: list[Experience] = []
    for block in result.sections.get("experience", []):
        company, title, location = _company_and_title(block.header)
        if not (company or block.bullets):
            continue
        entry_id = ids.make("exp", company, title)
        if not title:
            notes.append(f"{entry_id}: no title found - check company/title split")
        experience.append(
            Experience(
                id=entry_id, company=company or "TODO company", title=title or "TODO title",
                location=location, start=block.dates[0], end=block.dates[1],
                highlights=[
                    Highlight(id=f"{entry_id}.h{i}", text=t)
                    for i, t in enumerate(block.bullets, start=1)
                ],
            )
        )

    education: list[Education] = []
    for block in result.sections.get("education", []):
        if not block.header:
            continue
        institution = block.header[0]
        degree = block.header[1] if len(block.header) > 1 else ""
        entry_id = ids.make("edu", institution)
        gpa = ""
        if match := re.search(r"GPA[:\s]*([\d.]+(?:\s*/\s*[\d.]+)?)", " ".join(block.header + block.bullets), re.I):
            gpa = match.group(1)
        education.append(
            Education(
                id=entry_id, institution=institution, degree=degree, gpa=gpa,
                start=block.dates[0], end=block.dates[1],
                highlights=[
                    Highlight(id=f"{entry_id}.h{i}", text=t)
                    for i, t in enumerate(block.bullets, start=1)
                ],
            )
        )

    projects: list[Project] = []
    for block in result.sections.get("projects", []):
        if not block.header:
            continue
        name = re.split(r"\s+[|·]\s+", block.header[0])[0].strip()
        entry_id = ids.make("proj", name)
        projects.append(
            Project(
                id=entry_id, name=name, start=block.dates[0], end=block.dates[1],
                highlights=[
                    Highlight(id=f"{entry_id}.h{i}", text=t)
                    for i, t in enumerate(block.bullets, start=1)
                ],
            )
        )

    skills = _skills_from(result.sections.get("skills", []))
    return (
        Profile(
            basics=result.basics, experience=experience, education=education,
            projects=projects, skills=skills,
        ),
        notes,
    )


def _skills_from(blocks: list[Block]) -> dict[str, list[str]]:
    """"Languages: Python, Go, SQL" -> {"Languages": [...]}. Uncategorised lines land
    under "Skills"."""
    out: dict[str, list[str]] = {}
    for block in blocks:
        for line in block.header + block.bullets:
            if ":" in line:
                label, _, rest = line.partition(":")
                category = label.strip() or "Skills"
            else:
                category, rest = "Skills", line
            items = [s.strip(" .;") for s in re.split(r"[,;|·•]", rest) if s.strip(" .;")]
            if items:
                out.setdefault(category, []).extend(items)
    return out
