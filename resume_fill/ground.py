"""The fabrication gate.

PLAN.md decision 5: strict grounding, hard block. Every claim must trace to profile.yaml
or to the evidence corpus. Unmatched job-description keywords are reported as gaps; they
are never inserted.

This is the module that makes decision 4 safe. An auto-iterate loop optimising keyword
coverage has exactly one cheap way to raise its score — invent keywords — so the loop is
only honest for as long as this gate holds. Everything here is therefore a hard failure
fed back to the tailor, not a warning printed at the end.

Four rules, in order of how often they catch something real:

  1. Every bullet cites at least one Source, and every cited id resolves.
  2. Every number in a bullet appears in what those Sources actually say.
  3. Every technology named in a bullet appears in those Sources, or is declared in
     profile.skills — the one concession, and the reason profile.example.yaml says to
     keep that block to things you would defend in an interview. Per-highlight skill
     tags do *not* get that licence: they are part of their own highlight's evidence,
     so citing job A cannot claim a tool tagged only on job B.

     "Appears" is a question about the concept, not the letters: "Postgres" and
     "PostgreSQL" are one tool, "CI/CD" and "continuous integration" are one practice, and
     a note that says "Dockerised" has named Docker. See supported_term. Rejecting those
     costs an iteration and teaches the model nothing except which synonym this gate
     happens to know — while the tailor prompt is simultaneously telling it to write in the
     posting's vocabulary.
  4. Every bullet is evidenced by the entry it is printed under. Rules 1-3 ask whether a
     claim is true of the candidate; this one asks whether it is true of *this job*, which
     is a different question and the one an interviewer asks.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from .document import CoverLetter, LinkedInDraft, ResumeDoc
from .lexicon import base_forms, derived_forms, equivalents, technical_tokens
from .profile import Profile
from .source import SourceIndex, resolve, supporting_text
from .textutil import contains_term, normalize, numbers, supports_number, term_in, truncate

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
    # The exact thing that was wrong — the term, the figure, the skill, the id. `detail` is
    # a sentence for a person to read; this is the same fact for code, so that repair() and
    # the gap report do not have to pull a quoted substring back out of English prose.
    subject: str = ""

    def __str__(self) -> str:
        return f"{self.where}: {self.detail}"


def _claims_against(
    text: str, supporting: str, declared: set[str], where: str, allowed: set[str] = frozenset()
) -> list[Violation]:
    """Rules 2 and 3, for one piece of prose.

    `allowed` exists for the cover letter: naming the company you are writing to is not a
    claim about yourself. Without it, applying to DeepMind or PostgreSQL Inc. would fail
    every draft, because a CamelCase company name is indistinguishable from a CamelCase
    product name to the term rule.
    """
    found: list[Violation] = []
    for claim in numbers(text):
        if not supports_number(supporting, claim):
            found.append(
                Violation(
                    "unsupported_number", where,
                    f'the figure "{claim}" does not appear in the cited source',
                    subject=claim,
                )
            )
    for term in technical_tokens(text):
        if supported_term(term, supporting, declared, allowed):
            continue
        found.append(
            Violation(
                "unsupported_term", where,
                f'"{term}" is not in the cited source and is not declared in profile.skills',
                subject=term,
            )
        )
    return found


def supported_term(
    term: str, supporting: str, declared: set[str], allowed: set[str] = frozenset()
) -> bool:
    """Is this technology backed by something written down — under any of its names?

    The literal spelling is checked first, then the other spellings of the same concept, then
    the name a derived word was built from. All three are the *same claim*; only the letters
    differ, and a gate that rejects on letters spends an iteration teaching the model to say
    "continuous integration" where the posting said "CI/CD".

    What this does not do is widen what may be claimed. Every accepted spelling still has to
    resolve to a concept the cited source or the declared-skills block actually names — see
    lexicon.EXPANSIONS for the rule on adding a pair.
    """
    for name in (term, *equivalents(term), *base_forms(term)):
        if term_in(name, declared) or term_in(name, allowed) or contains_term(supporting, name):
            return True
    # Last, and only against the cited source: a note reading "Dockerised the worker" is
    # evidence for Docker. Not checked against `declared`, which is a curated list of names
    # and would never hold a conjugated one.
    return any(contains_term(supporting, form) for form in derived_forms(term))


def check(doc: ResumeDoc, profile: Profile, index: SourceIndex) -> list[Violation]:
    """Every reason this document may not be rendered. Empty means it may."""
    violations: list[Violation] = []
    # The curated block only. A skill tagged on one job's highlight travels with that
    # highlight (it is part of its Source text) and licenses nothing outside it.
    declared = {s.casefold() for s in profile.declared_skills()}
    selected_ids: list[str] = []
    rejected: set[str] = set()
    # where -> the ids a bullet sitting under that entry may cite. See _check_attribution.
    owned: dict[str, set[str]] = {}

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
            owned[where] = {entry.source_id, *source.children}
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
        if misattributed := _check_attribution(index, bullet.source_ids, where, owned):
            violations.append(misattributed)
            continue
        violations.extend(
            _claims_against(bullet.text, supporting_text(index, bullet.source_ids), declared, where)
        )

    violations.extend(_check_skills(doc, profile))
    violations.extend(_check_prose(doc, index, declared, selected_ids))
    violations.extend(_check_certifications(doc, index))
    return violations


# Kinds that belong to exactly one entry, and so may only be cited under that entry. The
# blog corpus and the declared-skills block deliberately do not: evidence adds specifics to
# a bullet wherever it sits, and a declared skill is a fact about the person, not the job.
_ENTRY_KINDS = frozenset({"experience", "education", "project", "certification"})


def _check_attribution(
    index: SourceIndex, source_ids: list[str], where: str, owned: dict[str, set[str]]
) -> Violation | None:
    """Rule 4: a bullet must be evidenced by the entry it is printed under.

    Rules 1-3 police whether a claim is true of the *candidate*; this one polices whether it
    is true of *this job*. Without it a document that cites nothing but real ids still
    misattributes: the tailor's cheapest way to fill a page is to select one role and hang
    every good bullet off it, which reads as though work done elsewhere happened there. The
    facts survive, the employer next to them does not, and that is the version an interviewer
    catches.
    """
    own = owned.get(where.rsplit(".", 1)[0])
    if own is None:
        return None
    foreign = [
        sid for sid in source_ids
        if sid not in own and (src := index.get(sid)) is not None and src.kind in _ENTRY_KINDS
    ]
    if not foreign:
        return None
    labels = ", ".join(f"{sid} ({index[sid].label})" for sid in foreign)
    return Violation(
        "misattributed_bullet", where,
        f"is printed under one entry but cites another: {labels}",
    )


def _check_skills(doc: ResumeDoc, profile: Profile) -> list[Violation]:
    """The skills block is the highest-value place to fabricate and the easiest to check:
    it must be a subset of what profile.yaml declares."""
    declared = {s.casefold() for s in profile.all_skills()}
    found = []
    for category, skills in doc.skills.items():
        for skill in skills:
            # Same equivalence the bullets get: a record that says "Postgres" declares the
            # skill a block writing "PostgreSQL" is claiming.
            if not supported_term(skill, "", declared):
                found.append(
                    Violation(
                        "undeclared_skill", f"skills[{category}]",
                        f'"{skill}" is not listed in profile.skills or on any highlight',
                        subject=skill,
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


def check_letter(
    letter: CoverLetter, profile: Profile, index: SourceIndex, *, allowed_terms: Iterable[str] = ()
) -> list[Violation]:
    """The same gate, applied to prose.

    A cover letter is where invention is most tempting: it is expected to be enthusiastic,
    and nobody expects it to be checkable. So it is checked — every paragraph cites, every
    number is in the cited source, every technology is too.
    """
    declared = {s.casefold() for s in profile.declared_skills()}
    allowed = {t.casefold() for t in allowed_terms}
    violations: list[Violation] = []

    if not letter.paragraphs:
        violations.append(Violation("empty_letter", "letter", "has no paragraphs"))
    for where, paragraph in letter.cited():
        if not paragraph.text.strip():
            violations.append(Violation("empty_bullet", where, "is empty"))
            continue
        if not paragraph.source_ids:
            violations.append(
                Violation("uncited_bullet", where, f'cites nothing: "{truncate(paragraph.text, 70)}"')
            )
            continue
        _, missing = resolve(index, paragraph.source_ids)
        if missing:
            violations.append(
                Violation("unknown_source", where, f"cites unknown id(s): {', '.join(missing)}")
            )
            continue
        violations.extend(
            _claims_against(
                paragraph.text, supporting_text(index, paragraph.source_ids), declared, where, allowed
            )
        )
    return violations


def check_linkedin(draft: LinkedInDraft, profile: Profile, index: SourceIndex) -> list[Violation]:
    """The same gate again, for proposed profile copy.

    A LinkedIn profile is the most-read thing you write and the least reviewed. It is also
    the one output here that a human pastes somewhere by hand, so a claim that slips
    through is one nobody will ever check again.
    """
    declared = {s.casefold() for s in profile.declared_skills()}
    known_experience = {e.id for e in profile.experience}
    violations: list[Violation] = []

    for section in draft.experience:
        if section.source_id not in known_experience:
            violations.append(
                Violation("unknown_entry", f"experience[{section.source_id}]",
                          "no such role in profile.yaml")
            )

    for where, paragraph in draft.cited():
        if not paragraph.text.strip():
            violations.append(Violation("empty_bullet", where, "is empty"))
            continue
        if not paragraph.source_ids:
            violations.append(
                Violation("uncited_bullet", where, f'cites nothing: "{truncate(paragraph.text, 70)}"')
            )
            continue
        _, missing = resolve(index, paragraph.source_ids)
        if missing:
            violations.append(
                Violation("unknown_source", where, f"cites unknown id(s): {', '.join(missing)}")
            )
            continue
        violations.extend(
            _claims_against(paragraph.text, supporting_text(index, paragraph.source_ids), declared, where)
        )
    return violations


# -------------------------------------------------------------- repair ----

# Violations confined to one bullet. Removing the bullet removes the claim, and the rest of
# the document is untouched and still true.
_BULLET_LEVEL = frozenset({
    "unsupported_number", "unsupported_term", "uncited_bullet", "unknown_source",
    "misattributed_bullet", "empty_bullet",
})
# Violations about the entry itself. Its bullets go with it — they were describing a job
# that is not going on the page.
_ENTRY_LEVEL = frozenset({"unknown_entry", "wrong_section", "empty_entry"})

_LOCATOR = re.compile(
    r"^(?P<section>[a-z_]+)(?:\[(?P<key>[^\]]*)\])?(?:\.bullet(?P<bullet>\d+))?$"
)
_PARAGRAPH = re.compile(r"^paragraph(?P<index>\d+)$")


@dataclass
class Repair:
    """A rejected draft with the unsupportable parts cut out of it.

    The gate stays absolute — nothing here weakens what may be claimed. What changes is the
    *cost of being wrong*: one bad token in one bullet used to throw away fifteen good ones
    and a whole iteration with them, and with MAX_ITER at 4 that meant three unlucky drafts
    produced no document at all. A résumé missing one bullet is worth more than no résumé.

    `remaining` is what could not be cut away — a document that is wrong in a way removal
    does not fix (nothing left, or a violation whose location cannot be located). That is
    still a rejection, and the loop still retries it.
    """

    doc: ResumeDoc
    dropped: list[Violation] = field(default_factory=list)
    remaining: list[Violation] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.dropped)

    @property
    def ok(self) -> bool:
        """Usable: everything unsupportable is gone and there is still a résumé here."""
        return not self.remaining and not self.doc.is_empty()

    def summary(self) -> str:
        if not self.changed:
            return "nothing to repair"
        counts: dict[str, int] = {}
        for violation in self.dropped:
            counts[violation.kind] = counts.get(violation.kind, 0) + 1
        return ", ".join(f"{k}x{v}" for k, v in sorted(counts.items()))

    def notes(self) -> list[str]:
        """One line per removal, for report.md. What was cut is the honest half of the
        result: it is the list of things the record could not back."""
        return [f"{v.where} — {v.detail}" for v in self.dropped]


def repair(
    doc: ResumeDoc, profile: Profile, index: SourceIndex, violations: list[Violation]
) -> Repair:
    """Cut the unsupportable parts out of a rejected draft and re-check what is left.

    Removal only. Nothing is rewritten, nothing is substituted, and no claim survives that
    check() rejected — the returned document goes back through the same gate, and
    `remaining` is whatever it still fails on.
    """
    drop_entries: set[str] = set()
    drop_bullets: set[tuple[str, int]] = set()
    drop_skills: set[tuple[str, str]] = set()
    drop_certs: set[str] = set()
    clear: set[str] = set()
    acted: list[Violation] = []

    for violation in violations:
        match = _LOCATOR.match(violation.where)
        if match is None:
            continue
        section, key, bullet = match.group("section"), match.group("key"), match.group("bullet")
        if section in ("summary", "headline"):
            clear.add(section)
        elif section == "skills" and violation.kind == "undeclared_skill" and violation.subject:
            drop_skills.add((key or "", violation.subject))
        elif section == "certifications":
            drop_certs.add(key or "")
        elif violation.kind in _ENTRY_LEVEL:
            drop_entries.add(f"{section}[{key}]")
        elif violation.kind in _BULLET_LEVEL and bullet is not None:
            drop_bullets.add((f"{section}[{key}]", int(bullet)))
        else:
            continue
        acted.append(violation)

    repaired = doc.model_copy(deep=True)
    for section, entries in repaired.entry_groups():
        kept = []
        for entry in entries:
            where = f"{section}[{entry.source_id}]"
            if where in drop_entries:
                continue
            entry.bullets = [
                bullet
                for i, bullet in enumerate(entry.bullets, start=1)
                if (where, i) not in drop_bullets
            ]
            # An entry with every bullet cut is a company name and a date with nothing under
            # it. check() calls that empty_entry; there is no reason to print it either.
            if entry.bullets:
                kept.append(entry)
        entries[:] = kept

    for category, skill in drop_skills:
        if category in repaired.skills:
            repaired.skills[category] = [
                s for s in repaired.skills[category] if s.casefold() != skill.casefold()
            ]
    repaired.skills = {k: v for k, v in repaired.skills.items() if v}
    if drop_certs:
        repaired.certification_ids = [c for c in repaired.certification_ids if c not in drop_certs]
    if "summary" in clear:
        repaired.summary = ""
        repaired.summary_source_ids = []
    if "headline" in clear:
        repaired.headline = ""

    return Repair(doc=repaired, dropped=acted, remaining=check(repaired, profile, index))


@dataclass
class LetterRepair:
    """The same idea for the cover letter, one level coarser.

    Coarser also means costlier: cutting a paragraph out of a four-paragraph letter removes
    a quarter of it. So a repaired letter still has to be a letter — two paragraphs is the
    floor, below which the right answer is to write it again rather than ship a fragment.
    """

    letter: CoverLetter
    dropped: list[Violation] = field(default_factory=list)
    remaining: list[Violation] = field(default_factory=list)

    MIN_PARAGRAPHS = 2

    @property
    def changed(self) -> bool:
        return bool(self.dropped)

    @property
    def ok(self) -> bool:
        return not self.remaining and len(self.letter.paragraphs) >= self.MIN_PARAGRAPHS


def repair_letter(
    letter: CoverLetter,
    profile: Profile,
    index: SourceIndex,
    violations: list[Violation],
    *,
    allowed_terms: Iterable[str] = (),
) -> LetterRepair:
    drop: set[int] = set()
    acted: list[Violation] = []
    for violation in violations:
        match = _PARAGRAPH.match(violation.where)
        if match is None:
            continue
        drop.add(int(match.group("index")))
        acted.append(violation)

    repaired = letter.model_copy(deep=True)
    repaired.paragraphs = [
        paragraph for i, paragraph in enumerate(letter.paragraphs, start=1) if i not in drop
    ]
    return LetterRepair(
        letter=repaired,
        dropped=acted,
        remaining=check_letter(repaired, profile, index, allowed_terms=allowed_terms),
    )


# --------------------------------------------------------------- retry ----

_ADVICE = {
    "unsupported_number": "Delete the figure or cite the source that contains it. Do not round, "
                          "restate or extrapolate a number that is not written down.",
    "unsupported_term": "Remove the technology, or cite a source that names it. If the job wants "
                        "it and the record does not have it, leave it out — it is a gap, and the "
                        "report says so.",
    "misattributed_bullet": "A bullet may only cite the entry it appears under, or that "
                            "entry's own highlights. Work done at one employer cannot be "
                            "listed under another: select that entry separately and put the "
                            "bullet there.",
    "uncited_bullet": "Every bullet must list the source ids it came from.",
    "unknown_source": "Use ids exactly as they appear in the source catalogue.",
    "unknown_entry": "Select only entries that exist in the catalogue.",
    "wrong_section": "Put each entry under the section matching its kind.",
    "undeclared_skill": "The skills block may only contain skills already in the record.",
    "empty_entry": "Either write bullets for the entry or do not select it.",
    "empty_bullet": "Remove empty bullets.",
    "empty_letter": "Write the letter.",
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
        if violation.kind == "unsupported_term" and violation.subject:
            if normalize(violation.subject) not in {normalize(t) for t in out}:
                out.append(violation.subject)
    return out
