"""The fabrication gate.

PLAN.md decision 5: strict grounding, hard block. Every claim must trace to profile.yaml
or to the evidence corpus. Unmatched job-description keywords are reported as gaps; they
are never inserted.

This is the module that makes decision 4 safe. An auto-iterate loop optimising keyword
coverage has exactly one cheap way to raise its score — invent keywords — so the loop is
only honest for as long as this gate holds. Everything here is therefore a hard failure
fed back to the tailor, not a warning printed at the end.

Three rules, in order of how often they catch something real:

  1. Every bullet cites at least one Source, and every cited id resolves.
  2. Every number in a bullet appears in what those Sources actually say.
  3. Every technology named in a bullet appears in those Sources, or is declared in
     profile.skills — the one concession, and the reason profile.example.yaml says to
     keep that block to things you would defend in an interview. Per-highlight skill
     tags do *not* get that licence: they are part of their own highlight's evidence,
     so citing job A cannot claim a tool tagged only on job B.
"""

from __future__ import annotations

from dataclasses import dataclass

from .document import ResumeDoc
from .lexicon import technical_tokens
from .profile import Profile
from .source import SourceIndex, resolve, supporting_text
from .textutil import contains_term, normalize, numbers, supports_number, truncate

# Which Source kinds may fill which section of the document. Selecting a blog post as an
# "experience" entry would produce a job with no employer and no dates.
_ALLOWED_KINDS = {
    "experience": {"experience"},
    "projects": {"project"},
    "education": {"education"},
}


@dataclass(frozen=True)
class Violation:
    kind: str
    where: str
    detail: str

    def __str__(self) -> str:
        return f"{self.where}: {self.detail}"


def _claims_against(text: str, supporting: str, declared: set[str], where: str) -> list[Violation]:
    """Rules 2 and 3, for one piece of prose."""
    found: list[Violation] = []
    for claim in numbers(text):
        if not supports_number(supporting, claim):
            found.append(
                Violation(
                    "unsupported_number", where,
                    f'the figure "{claim}" does not appear in the cited source',
                )
            )
    for term in technical_tokens(text):
        if term.casefold() in declared or contains_term(supporting, term):
            continue
        found.append(
            Violation(
                "unsupported_term", where,
                f'"{term}" is not in the cited source and is not declared in profile.skills',
            )
        )
    return found


def check(doc: ResumeDoc, profile: Profile, index: SourceIndex) -> list[Violation]:
    """Every reason this document may not be rendered. Empty means it may."""
    violations: list[Violation] = []
    # The curated block only. A skill tagged on one job's highlight travels with that
    # highlight (it is part of its Source text) and licenses nothing outside it.
    declared = {s.casefold() for s in profile.declared_skills()}
    selected_ids: list[str] = []
    rejected: set[str] = set()

    for section, entries in doc.entry_groups():
        allowed = _ALLOWED_KINDS[section]
        for entry in entries:
            where = f"{section}[{entry.source_id}]"
            source = index.get(entry.source_id)
            if source is None:
                violations.append(
                    Violation("unknown_entry", where, "no such id in profile.yaml or the evidence corpus")
                )
                rejected.add(where)
                continue
            if source.kind not in allowed:
                violations.append(
                    Violation(
                        "wrong_section", where,
                        f"is a {source.kind} source but was placed under {section}",
                    )
                )
                rejected.add(where)
                continue
            selected_ids.append(entry.source_id)
            if not entry.bullets:
                violations.append(Violation("empty_entry", where, "was selected but given no bullets"))

    for where, bullet in doc.bullets():
        # The entry itself was already rejected; re-reporting each of its bullets would
        # bury the one thing the tailor has to fix under a dozen consequences of it.
        if where.rsplit(".", 1)[0] in rejected:
            continue
        if not bullet.text.strip():
            violations.append(Violation("empty_bullet", where, "is empty"))
            continue
        if not bullet.source_ids:
            violations.append(
                Violation("uncited_bullet", where, f'cites nothing: "{truncate(bullet.text, 70)}"')
            )
            continue
        _, missing = resolve(index, bullet.source_ids)
        if missing:
            violations.append(
                Violation("unknown_source", where, f"cites unknown id(s): {', '.join(missing)}")
            )
            continue
        violations.extend(
            _claims_against(bullet.text, supporting_text(index, bullet.source_ids), declared, where)
        )

    violations.extend(_check_skills(doc, profile))
    violations.extend(_check_prose(doc, index, declared, selected_ids))
    violations.extend(_check_certifications(doc, index))
    return violations


def _check_skills(doc: ResumeDoc, profile: Profile) -> list[Violation]:
    """The skills block is the highest-value place to fabricate and the easiest to check:
    it must be a subset of what profile.yaml declares."""
    declared = {s.casefold(): s for s in profile.all_skills()}
    found = []
    for category, skills in doc.skills.items():
        for skill in skills:
            if skill.casefold() not in declared:
                found.append(
                    Violation(
                        "undeclared_skill", f"skills[{category}]",
                        f'"{skill}" is not listed in profile.skills or on any highlight',
                    )
                )
    return found


def _check_prose(
    doc: ResumeDoc, index: SourceIndex, declared: set[str], selected_ids: list[str]
) -> list[Violation]:
    """The headline and summary are about the person, so they are checked against the whole
    selection rather than one entry — but they are still checked."""
    scope = list(dict.fromkeys([*doc.summary_source_ids, *selected_ids]))
    _, missing = resolve(index, doc.summary_source_ids)
    found = [
        Violation("unknown_source", "summary", f"cites unknown id(s): {', '.join(missing)}")
    ] if missing else []
    supporting = supporting_text(index, scope)
    if doc.summary.strip():
        found.extend(_claims_against(doc.summary, supporting, declared, "summary"))
    if doc.headline.strip():
        found.extend(_claims_against(doc.headline, supporting, declared, "headline"))
    return found


def _check_certifications(doc: ResumeDoc, index: SourceIndex) -> list[Violation]:
    found = []
    for cert_id in doc.certification_ids:
        source = index.get(cert_id)
        if source is None or source.kind != "certification":
            found.append(
                Violation("unknown_entry", f"certifications[{cert_id}]", "no such certification in profile.yaml")
            )
    return found


# --------------------------------------------------------------- retry ----

_ADVICE = {
    "unsupported_number": "Delete the figure or cite the source that contains it. Do not round, "
                          "restate or extrapolate a number that is not written down.",
    "unsupported_term": "Remove the technology, or cite a source that names it. If the job wants "
                        "it and the record does not have it, leave it out — it is a gap, and the "
                        "report says so.",
    "uncited_bullet": "Every bullet must list the source ids it came from.",
    "unknown_source": "Use ids exactly as they appear in the source catalogue.",
    "unknown_entry": "Select only entries that exist in the catalogue.",
    "wrong_section": "Put each entry under the section matching its kind.",
    "undeclared_skill": "The skills block may only contain skills already in the record.",
    "empty_entry": "Either write bullets for the entry or do not select it.",
    "empty_bullet": "Remove empty bullets.",
}


def feedback(violations: list[Violation], limit: int = 25) -> str:
    """What the tailor is told on retry. Specific, and it names the fix — a retry prompt
    that only says "that was wrong" gets the same answer back."""
    if not violations:
        return ""
    lines = ["The previous draft was REJECTED. Fix every item below and return the whole document again."]
    for violation in violations[:limit]:
        lines.append(f"- [{violation.kind}] {violation}")
    if len(violations) > limit:
        lines.append(f"- ... and {len(violations) - limit} more of the same kinds")
    kinds = list(dict.fromkeys(v.kind for v in violations))
    lines.append("")
    lines.extend(f"{kind}: {_ADVICE[kind]}" for kind in kinds if kind in _ADVICE)
    return "\n".join(lines)


def summarize(violations: list[Violation]) -> str:
    counts: dict[str, int] = {}
    for violation in violations:
        counts[violation.kind] = counts.get(violation.kind, 0) + 1
    return ", ".join(f"{k}×{v}" for k, v in sorted(counts.items())) or "none"


def unsupported_terms(violations: list[Violation]) -> list[str]:
    """The technologies the draft tried to claim and could not. These are the honest gaps,
    and report.md prints them as such."""
    out = []
    for violation in violations:
        if violation.kind == "unsupported_term":
            term = violation.detail.split('"')[1] if '"' in violation.detail else violation.detail
            if normalize(term) not in {normalize(t) for t in out}:
                out.append(term)
    return out
