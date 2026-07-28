"""Proposed LinkedIn copy, as a diff. You paste it in.

PLAN.md decision 1, and it is not a limitation to work around — it is the finding.
LinkedIn has no public write API for profile fields: the free tier (Sign In with LinkedIn /
OIDC) is read-only, `w_member_social` writes to the *feed* and not the profile, and profile
write sits behind partner programmes that are effectively closed. The remaining option
would be to automate the live account, which violates the User Agreement §8.2 and risks a
ban on the exact profile this is meant to polish.

So this module prints and never writes. It has no LinkedIn client, no session, no
credentials, and no code path that touches linkedin.com.

What it does have is the same grounding gate as everything else, because a LinkedIn
profile is the most-read thing you write and the least reviewed.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from .config import Settings
from .document import LinkedInDraft
from .evidence import Corpus
from .ground import Violation, check_linkedin
from .ground import feedback as ground_feedback
from .llm import LLMCall, LLMError
from .profile import Profile
from .tailor import catalogue

_SYSTEM = """You write LinkedIn profile copy under a hard verification step.

A validator re-reads every line and rejects the draft if a claim cannot be traced to the \
source catalogue: every paragraph cites source ids, every number appears in the cited \
source, every technology appears there or in DECLARED SKILLS.

LinkedIn copy is written in the first person and is allowed to be warmer than a résumé. It \
is not allowed to be vaguer: "led initiatives across the stack" says nothing and cannot be \
cited. Prefer one concrete, sourced sentence over three general ones.

Return only JSON."""

_SCHEMA = """{
  "headline": {"text": "under 220 characters", "source_ids": ["..."]},
  "about": [{"text": "one paragraph", "source_ids": ["..."]}],
  "experience": [{"source_id": "exp-...", "paragraphs": [{"text": "...", "source_ids": ["..."]}]}]
}"""

_USER = """Write LinkedIn profile copy from the catalogue below.

=== SOURCE CATALOGUE (the only facts you may use) ===
{catalogue}

=== CURRENT PROFILE COPY (what is on the profile today) ===
{current}

=== RULES ===
1. Headline: under 220 characters, what you do and what you are good at. No buzzwords, no
   "|"-separated keyword lists, no emoji.
2. About: {about_paragraphs} short paragraphs, first person, about {about_words} words total.
   Open with the thing you would actually lead with in a conversation.
3. Experience: for each role in the catalogue worth describing, 1-2 paragraphs of what you
   did there. Select roles by id.
4. Every paragraph lists its source ids. Numbers only if they appear in the cited source.
   Technologies only if named there or in DECLARED SKILLS.
5. Improve on the current copy where you can, but do not contradict it, and do not restate
   the résumé verbatim - this is read by people, not parsers.

=== OUTPUT ===
Return JSON exactly in this shape:
{schema}
{feedback}"""


@dataclass
class CurrentCopy:
    """What the profile says today, for the left-hand side of the diff."""

    headline: str = ""
    about: str = ""
    experience: dict[str, str] = field(default_factory=dict)


@dataclass
class DraftResult:
    draft: LinkedInDraft
    current: CurrentCopy
    violations: list[Violation]
    attempts: int

    @property
    def ok(self) -> bool:
        return not self.violations


def current_copy(profile: Profile, export_dir: Path | None = None) -> CurrentCopy:
    """Prefer the LinkedIn export, because that is literally what is on the profile.

    profile.yaml is the fallback and is only approximately right: `init` merges résumé
    bullets over the export's descriptions, so by the time you run this the record may
    describe the job better than LinkedIn does. Diffing against the record would then hide
    exactly the change you want to make.
    """
    if export_dir and export_dir.is_dir():
        from .ingest.linkedin import _find, get, read_csv

        rows = read_csv(_find(export_dir, "Profile"))
        row = rows[0] if rows else {}
        positions = read_csv(_find(export_dir, "Positions"))
        by_company = {
            get(p, "Company Name", "Company").casefold(): get(p, "Description")
            for p in positions
        }
        experience = {
            entry.id: by_company.get(entry.company.casefold(), "")
            for entry in profile.experience
        }
        return CurrentCopy(
            headline=get(row, "Headline"),
            about=get(row, "Summary"),
            experience=experience,
        )

    return CurrentCopy(
        headline=profile.basics.headline,
        about=profile.basics.summary,
        experience={e.id: "\n".join(h.text for h in e.highlights) for e in profile.experience},
    )


def build_prompt(
    profile: Profile, corpus: Corpus | None, current: CurrentCopy, cfg: Settings, *, feedback: str = ""
) -> tuple[str, str]:
    current_block = "\n".join(
        [
            f"Headline: {current.headline or '(empty)'}",
            f"About: {current.about or '(empty)'}",
            *[
                f"[{entry_id}]: {text or '(empty)'}"
                for entry_id, text in current.experience.items()
            ],
        ]
    )
    user = _USER.format(
        catalogue=catalogue(profile, corpus),
        current=current_block,
        about_paragraphs=cfg.LINKEDIN_ABOUT_PARAGRAPHS,
        about_words=cfg.LINKEDIN_ABOUT_WORDS,
        schema=_SCHEMA,
        feedback=f"\n=== WHY THE LAST ATTEMPT WAS REJECTED ===\n{feedback}\n" if feedback else "",
    )
    return _SYSTEM, user


def write(
    profile: Profile,
    corpus: Corpus | None,
    cfg: Settings,
    llm_call: LLMCall,
    *,
    export_dir: Path | None = None,
) -> DraftResult:
    """Grounding-retry loop, same shape as the cover letter's."""
    current = current_copy(profile, export_dir)
    index = profile.sources()
    if corpus:
        index.update(corpus.sources())

    draft, violations, feedback = LinkedInDraft(), [], ""
    attempts = 0
    while attempts < max(1, cfg.MAX_ITER):
        attempts += 1
        system, user = build_prompt(profile, corpus, current, cfg, feedback=feedback)
        data = llm_call(system, user)
        try:
            draft = LinkedInDraft.model_validate(data)
        except ValidationError as exc:
            raise LLMError(f"the model returned profile copy that does not fit the schema:\n{exc}") from exc
        violations = check_linkedin(draft, profile, index)
        if not violations:
            break
        feedback = ground_feedback(violations)
    return DraftResult(draft=draft, current=current, violations=violations, attempts=attempts)


# ----------------------------------------------------------------- diff ----


def _diff(label: str, before: str, after: str) -> list[str]:
    """Word-wrapped unified diff. Wrapping first is what makes it readable: LinkedIn copy
    is a handful of very long lines, and diffing those whole reports every paragraph as
    entirely changed."""
    import textwrap

    def lines(text: str) -> list[str]:
        out: list[str] = []
        for block in (text or "").split("\n"):
            out.extend(textwrap.wrap(block, 88) or [""])
        return out

    delta = list(
        difflib.unified_diff(lines(before), lines(after), fromfile=f"current {label}",
                             tofile=f"proposed {label}", lineterm="")
    )
    return delta or [f"--- {label}: unchanged"]


def render(result: DraftResult, profile: Profile) -> str:
    """The whole output: the copy to paste, then the diff against what is there now."""
    draft, current = result.draft, result.current
    by_id = {e.id: e for e in profile.experience}
    lines = [
        f"# LinkedIn draft — {profile.basics.name}",
        "",
        f"Generated {date.today().isoformat()}. {result.attempts} iteration(s).",
        "",
        "LinkedIn has no public write API for profile fields, and automating the live account",
        "violates the User Agreement §8.2 — on the exact profile this is meant to polish. So this",
        "is copy to paste, by you, deliberately.",
        "",
    ]

    if result.violations:
        lines += [
            "## Rejected by the grounding gate",
            "",
            "The draft below is the last attempt and still contains unsupported claims. Do not",
            "paste it as-is.",
            "",
            *[f"- [{v.kind}] {v}" for v in result.violations],
            "",
        ]

    lines += ["## Headline", "", "```", (draft.headline.text if draft.headline else ""), "```", ""]
    lines += _fenced_diff("headline", current.headline, draft.headline.text if draft.headline else "")

    lines += ["## About", "", "```", draft.about_text(), "```", ""]
    lines += _fenced_diff("about", current.about, draft.about_text())

    for section in draft.experience:
        entry = by_id.get(section.source_id)
        title = entry.label if entry else section.source_id
        lines += [f"## Experience — {title}", "", "```", section.text(), "```", ""]
        lines += _fenced_diff(section.source_id, current.experience.get(section.source_id, ""), section.text())

    lines += ["## Citations", ""]
    index = profile.sources()
    for where, paragraph in draft.cited():
        labels = [index[sid].label for sid in paragraph.source_ids if sid in index]
        lines.append(f"- **{where}** — {paragraph.text}")
        lines.append(f"  - source: {'; '.join(labels) or '(none)'}")
    lines.append("")
    return "\n".join(lines)


def _fenced_diff(label: str, before: str, after: str) -> list[str]:
    return ["<details><summary>diff vs current</summary>", "", "```diff",
            *_diff(label, before, after), "```", "", "</details>", ""]
