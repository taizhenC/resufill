"""LinkedIn data export (CSV archive) -> profile.yaml seed.

This is the skeleton source: employers, titles, dates, school, degree. It is structured
and it is yours, which is exactly what a blog is not. Descriptions in the export are
often empty or a wall of prose, so the *bullets* usually come from the résumé PDF
instead — see ingest/resume_pdf.py and the merge in cli.cmd_init.

Every file is optional and every column name is matched loosely: LinkedIn has renamed
these columns before ("Started On" vs "Start Date") and will again.
"""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from ..profile import (
    Basics,
    Certification,
    Education,
    Experience,
    Highlight,
    Link,
    Profile,
    Project,
    slug,
)

_MONTHS = {
    m.casefold(): i
    for i, m in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1
    )
}
_BULLET_PREFIX = re.compile(r"^\s*[-•‣▪·*◦o]\s+")


class IdMaker:
    """Stable, readable, unique ids. Readable matters: these end up in resume.json and in
    report.md, where a human has to tell at a glance which job a bullet came from."""

    def __init__(self) -> None:
        self._used: set[str] = set()

    def make(self, *parts: str) -> str:
        base = "-".join(slug(p, 22) for p in parts if p) or "item"
        candidate, n = base, 2
        while candidate in self._used:
            candidate, n = f"{base}-{n}", n + 1
        self._used.add(candidate)
        return candidate


def parse_date(value: str) -> str:
    """LinkedIn writes "Jun 2024", "2024", or "06/2024". Normalise to "YYYY-MM" (or "YYYY")."""
    text = (value or "").strip()
    if not text:
        return ""
    if match := re.fullmatch(r"([A-Za-z]{3,9})\s+(\d{4})", text):
        month = _MONTHS.get(match.group(1)[:3].casefold())
        return f"{match.group(2)}-{month:02d}" if month else match.group(2)
    if match := re.fullmatch(r"(\d{1,2})[/-](\d{4})", text):
        return f"{match.group(2)}-{int(match.group(1)):02d}"
    if match := re.fullmatch(r"(\d{4})-(\d{1,2})(?:-\d{1,2})?", text):
        return f"{match.group(1)}-{int(match.group(2)):02d}"
    if re.fullmatch(r"\d{4}", text):
        return text
    return text


def split_description(text: str) -> list[str]:
    """A LinkedIn description is one blob. Split it into the units a résumé bullet is
    written from: explicit bullets if there are any, otherwise paragraphs."""
    lines = [_BULLET_PREFIX.sub("", ln).strip() for ln in (text or "").splitlines()]
    items = [ln for ln in lines if len(ln) > 2]
    return items


def _find(export_dir: Path, *names: str) -> Path | None:
    """Locate a CSV by name, case- and space-insensitively (archives differ by locale)."""
    if not export_dir.is_dir():
        return None
    wanted = {re.sub(r"[^a-z]", "", n.casefold()) for n in names}
    for path in export_dir.rglob("*.csv"):
        if re.sub(r"[^a-z]", "", path.stem.casefold()) in wanted:
            return path
    return None


def read_csv(path: Path | None) -> list[dict[str, str]]:
    """Read a LinkedIn CSV, skipping the "Notes:" preamble some archives put above the header.

    The header is the first line whose field count matches the widest line following it —
    cheaper and more robust than hardcoding the column names we are about to look up loosely.
    """
    if path is None or not path.exists():
        return []
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return []
    header_idx = max(range(len(rows)), key=lambda i: (len(rows[i]), -i))
    header = [h.strip() for h in rows[header_idx]]
    out = []
    for row in rows[header_idx + 1 :]:
        if not any(cell.strip() for cell in row):
            continue
        out.append({header[i]: (row[i].strip() if i < len(row) else "") for i in range(len(header))})
    return out


def get(row: dict[str, str], *names: str) -> str:
    """Column lookup that survives LinkedIn renaming "Started On" to "Start Date"."""
    normalized = {re.sub(r"[^a-z]", "", k.casefold()): v for k, v in row.items()}
    for name in names:
        value = normalized.get(re.sub(r"[^a-z]", "", name.casefold()))
        if value:
            return value.strip()
    return ""


# --------------------------------------------------------------- sections ----


def _basics(export_dir: Path) -> Basics:
    rows = read_csv(_find(export_dir, "Profile"))
    row = rows[0] if rows else {}
    name = " ".join(p for p in (get(row, "First Name"), get(row, "Last Name")) if p)

    emails = read_csv(_find(export_dir, "Email Addresses", "Emails"))
    primary = next((e for e in emails if get(e, "Primary").casefold().startswith("y")), None)
    email = get(primary or (emails[0] if emails else {}), "Email Address", "Email")

    phones = read_csv(_find(export_dir, "PhoneNumbers", "Phone Numbers"))
    phone = get(phones[0], "Number", "Phone Number") if phones else ""

    links = []
    for url in re.split(r"[,\s]+", get(row, "Websites")):
        # The export writes websites as "PERSONAL:(https://...)" — keep only the URL.
        if match := re.search(r"https?://\S+", url.rstrip(")")):
            links.append(Link(label="", url=match.group(0)))

    return Basics(
        name=name or "TODO your name",
        headline=get(row, "Headline"),
        email=email,
        phone=phone,
        location=get(row, "Geo Location", "Location"),
        links=links,
    )


def _experience(rows: list[dict[str, str]], ids: IdMaker) -> list[Experience]:
    out = []
    for row in rows:
        company, title = get(row, "Company Name", "Company"), get(row, "Title", "Position")
        if not (company or title):
            continue
        entry_id = ids.make("exp", company, title)
        highlights = [
            Highlight(id=f"{entry_id}.h{i}", text=text)
            for i, text in enumerate(split_description(get(row, "Description")), start=1)
        ]
        out.append(
            Experience(
                id=entry_id,
                company=company or "TODO company",
                title=title or "TODO title",
                location=get(row, "Location"),
                start=parse_date(get(row, "Started On", "Start Date")),
                end=parse_date(get(row, "Finished On", "End Date")),
                highlights=highlights,
            )
        )
    return out


def _education(rows: list[dict[str, str]], ids: IdMaker) -> list[Education]:
    out = []
    for row in rows:
        school = get(row, "School Name", "School")
        if not school:
            continue
        entry_id = ids.make("edu", school)
        notes = split_description(get(row, "Notes", "Activities"))
        out.append(
            Education(
                id=entry_id,
                institution=school,
                degree=get(row, "Degree Name", "Degree"),
                start=parse_date(get(row, "Start Date", "Started On")),
                end=parse_date(get(row, "End Date", "Finished On")),
                highlights=[
                    Highlight(id=f"{entry_id}.h{i}", text=t) for i, t in enumerate(notes, start=1)
                ],
            )
        )
    return out


def _projects(rows: list[dict[str, str]], ids: IdMaker) -> list[Project]:
    out = []
    for row in rows:
        title = get(row, "Title", "Name")
        if not title:
            continue
        entry_id = ids.make("proj", title)
        items = split_description(get(row, "Description"))
        out.append(
            Project(
                id=entry_id,
                name=title,
                url=get(row, "Url", "URL"),
                start=parse_date(get(row, "Started On", "Start Date")),
                end=parse_date(get(row, "Finished On", "End Date")),
                highlights=[
                    Highlight(id=f"{entry_id}.h{i}", text=t) for i, t in enumerate(items, start=1)
                ],
            )
        )
    return out


def _certifications(rows: list[dict[str, str]], ids: IdMaker) -> list[Certification]:
    out = []
    for row in rows:
        name = get(row, "Name", "Title")
        if not name:
            continue
        out.append(
            Certification(
                id=ids.make("cert", name),
                name=name,
                issuer=get(row, "Authority", "Issuer"),
                date=parse_date(get(row, "Started On", "Issued On", "Start Date")),
                url=get(row, "Url", "URL"),
            )
        )
    return out


def load_export(export_dir: Path) -> Profile:
    """Read whatever of the archive is present. Missing files are not an error — a Basic
    export contains a different set of CSVs than a Complete one."""
    ids = IdMaker()
    skills = [get(r, "Name", "Skill") for r in read_csv(_find(export_dir, "Skills"))]
    return Profile(
        basics=_basics(export_dir),
        experience=_experience(read_csv(_find(export_dir, "Positions")), ids),
        education=_education(read_csv(_find(export_dir, "Education")), ids),
        projects=_projects(read_csv(_find(export_dir, "Projects")), ids),
        certifications=_certifications(read_csv(_find(export_dir, "Certifications")), ids),
        # One flat group: LinkedIn's skill list has no categories, and inventing them here
        # would be a guess. Split it by hand once, in the file.
        skills={"Skills": [s for s in skills if s]} if any(skills) else {},
    )
