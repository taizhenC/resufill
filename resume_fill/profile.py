"""`profile.yaml` — the canonical record of your career, and the thing every claim is
checked against.

A blog is narrative: it has no employers, titles, dates, degree or contact details
(PLAN.md §2). So the blog cannot be the source of truth; it is an evidence layer over
this file. Everything here carries a stable id, because ids are what make a bullet
traceable and therefore what make the fabrication gate possible.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError

from .source import Source, SourceIndex
from .textutil import truncate

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


class ProfileError(RuntimeError):
    """profile.yaml is missing, unreadable, or does not describe a person."""


def slug(text: str, limit: int = 28) -> str:
    """Ids get read by a human in report.md, so a truncated id ends on a whole word rather
    than mid-syllable ("backend-engineer", not "backend-engineer-inter")."""
    out = re.sub(r"[^a-z0-9]+", "-", (text or "").casefold()).strip("-")
    if len(out) <= limit:
        return out or "x"
    cut = out[:limit]
    if "-" in cut and out[limit] != "-":
        cut = cut.rsplit("-", 1)[0]
    return cut.strip("-") or out[:limit].strip("-") or "x"


def format_month(value: str) -> str:
    """"2024-06" -> "Jun 2024". Anything that is not YYYY-MM is passed through untouched,
    so a hand-written "Summer 2024" survives editing."""
    match = re.fullmatch(r"(\d{4})-(\d{1,2})", (value or "").strip())
    if not match:
        return (value or "").strip()
    year, month = match.group(1), int(match.group(2))
    return f"{_MONTHS[month - 1]} {year}" if 1 <= month <= 12 else year


def format_range(start: str, end: str) -> str:
    """An empty end date means the job is current — that is the convention throughout."""
    left, right = format_month(start), format_month(end) or "Present"
    return f"{left} – {right}" if left else right


def _sort_key(entry: DatedEntry) -> tuple:
    """Most recent first, current roles above finished ones."""
    end = (entry.end or "").strip()
    return (1 if not end else 0, end, entry.start or "")


class Link(BaseModel):
    label: str = ""
    url: str


class Basics(BaseModel):
    name: str
    headline: str = ""
    # The LinkedIn "About" section, seeded from the export's Summary field. Kept so
    # `linkedin draft` can diff proposed copy against what is actually on the profile.
    summary: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    links: list[Link] = Field(default_factory=list)

    def contact_line(self) -> str:
        parts = [self.location, self.phone, self.email] + [link.url for link in self.links]
        return " | ".join(p for p in parts if p)


class Highlight(BaseModel):
    """One recorded fact about one entry. This is the granularity the tailor cites."""

    id: str
    text: str
    skills: list[str] = Field(default_factory=list)


class DatedEntry(BaseModel):
    id: str
    start: str = ""
    end: str = ""  # empty means present

    @property
    def dates(self) -> str:
        return format_range(self.start, self.end)


class Experience(DatedEntry):
    company: str
    title: str
    location: str = ""
    summary: str = ""
    highlights: list[Highlight] = Field(default_factory=list)

    @property
    def label(self) -> str:
        return f"{self.company} - {self.title}"


class Education(DatedEntry):
    institution: str
    degree: str = ""
    field_of_study: str = ""
    location: str = ""
    gpa: str = ""
    highlights: list[Highlight] = Field(default_factory=list)

    @property
    def label(self) -> str:
        degree = " ".join(p for p in (self.degree, self.field_of_study) if p)
        return f"{self.institution} - {degree}" if degree else self.institution


class Project(DatedEntry):
    name: str
    url: str = ""
    summary: str = ""
    highlights: list[Highlight] = Field(default_factory=list)

    @property
    def label(self) -> str:
        return self.name


class Certification(BaseModel):
    id: str
    name: str
    issuer: str = ""
    date: str = ""
    url: str = ""

    @property
    def label(self) -> str:
        return f"{self.name} ({self.issuer})" if self.issuer else self.name


class Profile(BaseModel):
    basics: Basics
    experience: list[Experience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    # Free-form categories ("Languages", "Frameworks", ...) so the résumé's skills block
    # can be reordered per role without a schema change.
    skills: dict[str, list[str]] = Field(default_factory=dict)
    certifications: list[Certification] = Field(default_factory=list)

    # ------------------------------------------------------------------ views --

    def sorted_experience(self) -> list[Experience]:
        return sorted(self.experience, key=_sort_key, reverse=True)

    def sorted_education(self) -> list[Education]:
        return sorted(self.education, key=_sort_key, reverse=True)

    def sorted_projects(self) -> list[Project]:
        return sorted(self.projects, key=_sort_key, reverse=True)

    @staticmethod
    def _dedupe(skills: list[str]) -> list[str]:
        seen, unique = set(), []
        for skill in skills:
            key = skill.casefold().strip()
            if key and key not in seen:
                seen.add(key)
                unique.append(skill.strip())
        return unique

    def declared_skills(self) -> list[str]:
        """The curated skills block, flattened.

        A skill listed *here* is assertable anywhere: it may appear in a bullet without the
        bullet's own cited source spelling it out. That is the one concession the grounding
        gate makes, which is why this block has to be curated by hand rather than scraped
        wide — and why per-highlight skill tags deliberately do not get the same licence.
        A tag on one job's highlight is evidence for that highlight, not a global claim.
        """
        return self._dedupe([s for group in self.skills.values() for s in group])

    def all_skills(self) -> list[str]:
        """Every skill claimed anywhere: the curated block plus per-highlight tags.

        Used for the "may the résumé's skills block list this?" question, where a tool you
        used on one job counts — and for the tailor's catalogue. Not used for the grounding
        concession; see declared_skills.
        """
        tagged = [
            skill
            for entry in (*self.experience, *self.education, *self.projects)
            for highlight in entry.highlights
            for skill in highlight.skills
        ]
        return self._dedupe(self.declared_skills() + tagged)

    # --------------------------------------------------------------- sources --

    def sources(self) -> SourceIndex:
        """Flatten the record into the provenance index ground.py checks against.

        Each entry becomes a Source, each of its highlights becomes a narrower Source
        nested under it, and the skills block becomes one Source of its own so a bullet
        may cite `skills` for a tool it used but never wrote a highlight about.
        """
        index: SourceIndex = {}

        def add_entry(entry, kind: str, header: str) -> None:
            child_ids = []
            for highlight in entry.highlights:
                index[highlight.id] = Source(
                    id=highlight.id,
                    kind=kind,
                    text=f"{header}\n{highlight.text}",
                    label=f"{entry.label}: {truncate(highlight.text, 60)}",
                    skills=tuple(highlight.skills),
                )
                child_ids.append(highlight.id)
            body = "\n".join([header, getattr(entry, "summary", "") or ""]).strip()
            index[entry.id] = Source(
                id=entry.id,
                kind=kind,
                text=body,
                label=entry.label,
                children=tuple(child_ids),
            )

        for exp in self.experience:
            add_entry(exp, "experience", f"{exp.company} | {exp.title} | {exp.location} | {exp.dates}")
        for edu in self.education:
            add_entry(edu, "education", f"{edu.institution} | {edu.label} | {edu.gpa} | {edu.dates}")
        for proj in self.projects:
            add_entry(proj, "project", f"{proj.name} | {proj.url} | {proj.dates}")
        for cert in self.certifications:
            index[cert.id] = Source(
                id=cert.id, kind="certification", text=f"{cert.name} | {cert.issuer} | {cert.date}",
                label=cert.label,
            )
        skills = self.all_skills()
        if skills:
            index["skills"] = Source(
                id="skills", kind="skills", text=", ".join(skills),
                label="declared skills", skills=tuple(skills),
            )
        return index


# ------------------------------------------------------------------- io ----


def load_profile(path: Path) -> Profile:
    if not path.exists():
        raise ProfileError(f"no profile at {path} - run `resume-fill init` to bootstrap one")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ProfileError(f"{path} is not valid YAML: {exc}") from exc
    try:
        return Profile.model_validate(raw)
    except ValidationError as exc:
        raise ProfileError(f"{path} does not match the profile schema:\n{exc}") from exc


def dump_profile(profile: Profile, path: Path, *, note: str = "") -> None:
    body = yaml.safe_dump(
        profile.model_dump(mode="json"), sort_keys=False, allow_unicode=True, width=100
    )
    header = f"# resume-fill profile - canonical career record. Generated {date.today().isoformat()}.\n"
    if note:
        header += "".join(f"# {line}\n" for line in note.splitlines())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + body, encoding="utf-8")
