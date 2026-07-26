"""The atomic unit of provenance.

Every claim the tool is allowed to make traces to exactly one of these. `profile.yaml`
produces them (jobs, degrees, projects, skills) and the blog corpus produces them
(paragraphs of narrative). ground.py never looks at anything else: if a bullet cites an
id that is not in the index, or says something the cited Source's text does not support,
the document is rejected.
"""

from dataclasses import dataclass, field

# id -> Source. Built fresh for every run from profile.yaml + data/evidence.json.
SourceIndex = dict[str, "Source"]


@dataclass(frozen=True)
class Source:
    id: str
    kind: str  # experience | education | project | certification | skills | evidence
    text: str  # everything the source actually says, concatenated and searchable
    label: str  # human-readable, for report.md ("Acme Corp - Software Engineer")
    skills: tuple[str, ...] = field(default=())
    # Ids of narrower sources nested inside this one (a job's bullets). Citing the parent
    # is allowed and covers all of them.
    children: tuple[str, ...] = field(default=())


def resolve(index: SourceIndex, ids: list[str]) -> tuple[list[Source], list[str]]:
    """Split cited ids into the ones that exist and the ones that do not."""
    found, missing = [], []
    for sid in ids:
        src = index.get(sid)
        (found.append(src) if src else missing.append(sid))
    return found, missing


def supporting_text(index: SourceIndex, ids: list[str]) -> str:
    """The union of what the cited sources say — plus, for a parent, what its children say.

    Citing a whole job should license a bullet drawn from any of that job's recorded
    highlights; it should not license anything from a *different* job.
    """
    seen: set[str] = set()
    parts: list[str] = []

    def add(sid: str) -> None:
        if sid in seen:
            return
        seen.add(sid)
        src = index.get(sid)
        if src is None:
            return
        parts.append(src.text)
        parts.extend(src.skills)
        for child in src.children:
            add(child)

    for sid in ids:
        add(sid)
    return "\n".join(parts)
