"""`resume-fill init` — merge the two seeds into one canonical record.

Neither seed is complete on its own. The LinkedIn export has the skeleton (employers,
titles, dates, school) but usually empty descriptions. The résumé PDF has the bullets and
the contact block but no reliable structure. So: LinkedIn decides *what entries exist* and
what they are called, the PDF fills in *what you did there*, and everything either of them
had to guess is reported so it gets corrected once, by hand, in the file.
"""

from __future__ import annotations

import re
from pathlib import Path

from .ingest import linkedin, resume_pdf
from .profile import Basics, Highlight, Profile

_CO_NOISE = re.compile(r"\b(inc|llc|ltd|corp|corporation|co|company|the|university|college)\b", re.I)


def _key(*parts: str) -> str:
    """A comparison key that survives "Acme, Inc." vs "Acme Corporation"."""
    text = _CO_NOISE.sub(" ", " ".join(parts))
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def _same_entry(a: str, b: str) -> bool:
    ka, kb = _key(a), _key(b)
    if not ka or not kb:
        return False
    return ka == kb or ka in kb or kb in ka


def _renumber(entry_id: str, texts: list[str], skills_by_text: dict[str, list[str]]) -> list[Highlight]:
    return [
        Highlight(id=f"{entry_id}.h{i}", text=text, skills=skills_by_text.get(text, []))
        for i, text in enumerate(texts, start=1)
    ]


def _merge_entries(skeleton: list, detail: list, match_fields: tuple[str, ...]) -> list:
    """Keep the skeleton's identity, take the detail's bullets, append what only detail had.

    Bullets from the résumé PDF beat LinkedIn descriptions every time: they were already
    written to be read by a recruiter, and most LinkedIn descriptions are empty.
    """
    used: set[int] = set()
    merged = []
    for entry in skeleton:
        match_idx = None
        for i, other in enumerate(detail):
            if i in used:
                continue
            if any(_same_entry(getattr(entry, f, ""), getattr(other, f, "")) for f in match_fields):
                match_idx = i
                break
        if match_idx is None:
            merged.append(entry)
            continue
        other = detail[match_idx]
        used.add(match_idx)
        skills_by_text = {h.text: h.skills for h in (*entry.highlights, *other.highlights)}
        texts = [h.text for h in other.highlights] or [h.text for h in entry.highlights]
        update = {"highlights": _renumber(entry.id, texts, skills_by_text)}
        # The PDF is the better source for anything the export left blank.
        for attr in ("location", "start", "end", "summary", "gpa", "degree", "url"):
            if hasattr(entry, attr) and not getattr(entry, attr) and getattr(other, attr, ""):
                update[attr] = getattr(other, attr)
        merged.append(entry.model_copy(update=update))

    for i, other in enumerate(detail):
        if i not in used:
            merged.append(other)
    return merged


def _merge_basics(skeleton: Basics, detail: Basics) -> Basics:
    urls = {link.url.rstrip("/").casefold(): link for link in (*skeleton.links, *detail.links)}
    return Basics(
        name=skeleton.name if not skeleton.name.startswith("TODO") else detail.name,
        headline=skeleton.headline or detail.headline,
        summary=skeleton.summary or detail.summary,
        email=skeleton.email or detail.email,
        phone=skeleton.phone or detail.phone,
        location=skeleton.location or detail.location,
        links=list(urls.values()),
    )


def _merge_skills(skeleton: dict[str, list[str]], detail: dict[str, list[str]]) -> dict[str, list[str]]:
    """The résumé's categories win, because a curated "Languages / Frameworks / Tools"
    split is a judgement LinkedIn's flat endorsement list cannot reproduce. Anything the
    export knew about and the résumé did not is appended, uncategorised, to be filed."""
    out: dict[str, list[str]] = {k: list(v) for k, v in detail.items()}
    known = {s.casefold() for group in out.values() for s in group}
    extra = [s for group in skeleton.values() for s in group if s.casefold() not in known]
    if extra:
        out.setdefault("Skills", []).extend(extra)
    return out


def merge(skeleton: Profile, detail: Profile) -> Profile:
    return Profile(
        basics=_merge_basics(skeleton.basics, detail.basics),
        experience=_merge_entries(skeleton.experience, detail.experience, ("company", "title")),
        education=_merge_entries(skeleton.education, detail.education, ("institution",)),
        projects=_merge_entries(skeleton.projects, detail.projects, ("name",)),
        skills=_merge_skills(skeleton.skills, detail.skills),
        certifications=skeleton.certifications or detail.certifications,
    )


def audit(profile: Profile) -> list[str]:
    """Everything a human still has to look at. Printed by `init`, not raised: a seed that
    needs three corrections is still worth far more than an empty file."""
    todo: list[str] = []
    basics = profile.basics
    if not basics.name or basics.name.startswith("TODO"):
        todo.append("basics.name is not set")
    for field_name in ("email", "phone", "location"):
        if not getattr(basics, field_name):
            todo.append(f"basics.{field_name} is empty")
    if not profile.experience and not profile.projects:
        todo.append("no experience or projects found - the tailor will have nothing to select from")
    for entry in profile.experience:
        if entry.company.startswith("TODO") or entry.title.startswith("TODO"):
            todo.append(f"{entry.id}: company/title needs checking ({entry.company} / {entry.title})")
        if not entry.highlights:
            todo.append(f"{entry.id}: no bullets - add what you actually did, or it cannot be cited")
        if not entry.start:
            todo.append(f"{entry.id}: no start date")
    for entry in profile.education:
        if not entry.degree:
            todo.append(f"{entry.id}: no degree recorded")
    if not profile.skills:
        todo.append("skills is empty - the skills block is the only place a tool may be claimed "
                    "without a bullet backing it, so it is worth curating")
    return todo


def bootstrap(
    export_dir: Path | None, resume_path: Path | None
) -> tuple[Profile, list[str], list[str]]:
    """Returns (profile, sources_used, notes). At least one seed must exist."""
    used: list[str] = []
    notes: list[str] = []

    skeleton: Profile | None = None
    if export_dir and export_dir.is_dir():
        skeleton = linkedin.load_export(export_dir)
        counts = f"{len(skeleton.experience)} positions, {len(skeleton.education)} schools"
        used.append(f"LinkedIn export ({export_dir}): {counts}")

    detail: Profile | None = None
    if resume_path and resume_path.is_file():
        detail, pdf_notes = resume_pdf.to_profile(resume_path)
        bullets = sum(len(e.highlights) for e in (*detail.experience, *detail.projects))
        used.append(f"résumé PDF ({resume_path.name}): {len(detail.experience)} roles, {bullets} bullets")
        notes.extend(pdf_notes)

    if skeleton and detail:
        profile = merge(skeleton, detail)
    elif skeleton or detail:
        profile = skeleton or detail
    else:
        raise RuntimeError(
            "nothing to bootstrap from. Point --linkedin-export at an unpacked LinkedIn data "
            "archive, or --resume-pdf at an existing résumé, or both."
        )
    return profile, used, notes
