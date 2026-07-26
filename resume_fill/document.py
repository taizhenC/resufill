"""`resume.json` — the intermediate the tailor produces and everything downstream reads.

The model chooses *which* recorded entries to surface, in what order, and writes the
bullets. It does not get to state the company, the title or the dates: those are copied
from profile.yaml by id at render time. That is deliberate. A tailored bullet is a
rephrasing that grounding can police word by word; an employer name is a fact, and the
cheapest way to guarantee the facts are right is to never let them be generated.
"""

from __future__ import annotations

from collections.abc import Iterator

from pydantic import BaseModel, Field

SECTIONS = ("summary", "skills", "experience", "projects", "education", "certifications")


class Bullet(BaseModel):
    text: str
    # Which Sources license this sentence. Empty is a violation, not a default.
    source_ids: list[str] = Field(default_factory=list)


class SelectedEntry(BaseModel):
    """One profile entry the tailor chose to include, with the bullets it wrote for it."""

    source_id: str
    bullets: list[Bullet] = Field(default_factory=list)


class ResumeDoc(BaseModel):
    headline: str = ""
    summary: str = ""
    summary_source_ids: list[str] = Field(default_factory=list)
    experience: list[SelectedEntry] = Field(default_factory=list)
    projects: list[SelectedEntry] = Field(default_factory=list)
    education: list[SelectedEntry] = Field(default_factory=list)
    certification_ids: list[str] = Field(default_factory=list)
    # Must be a subset of what profile.yaml declares; ground.py enforces that.
    skills: dict[str, list[str]] = Field(default_factory=dict)
    section_order: list[str] = Field(default_factory=lambda: list(SECTIONS))

    def entry_groups(self) -> list[tuple[str, list[SelectedEntry]]]:
        return [
            ("experience", self.experience),
            ("projects", self.projects),
            ("education", self.education),
        ]

    def bullets(self) -> Iterator[tuple[str, Bullet]]:
        """Every bullet with a locator naming where it lives, for violation messages."""
        for section, entries in self.entry_groups():
            for entry in entries:
                for i, bullet in enumerate(entry.bullets, start=1):
                    yield f"{section}[{entry.source_id}].bullet{i}", bullet

    def bullet_text(self) -> str:
        return "\n".join(bullet.text for _, bullet in self.bullets())

    def skill_list(self) -> list[str]:
        return [skill for group in self.skills.values() for skill in group]

    def searchable_text(self) -> str:
        """Everything a keyword would have to be found in. Used by the scorer."""
        return "\n".join(
            [self.headline, self.summary, self.bullet_text(), ", ".join(self.skill_list())]
        )

    def ordered_sections(self) -> list[str]:
        """The tailor's order, with anything it forgot appended so nothing silently vanishes."""
        seen, order = set(), []
        for name in [*self.section_order, *SECTIONS]:
            if name in SECTIONS and name not in seen:
                seen.add(name)
                order.append(name)
        return order


class Paragraph(BaseModel):
    text: str
    source_ids: list[str] = Field(default_factory=list)


class CoverLetter(BaseModel):
    """The same contract as the résumé, one level coarser: a paragraph carries citations
    where a bullet does.

    A cover letter is where invention is most tempting — it is prose, it is expected to be
    enthusiastic, and nobody expects it to be checkable. It goes through exactly the same
    gate.
    """

    addressee: str = ""
    subject: str = ""
    paragraphs: list[Paragraph] = Field(default_factory=list)
    signoff: str = "Sincerely,"

    def cited(self) -> Iterator[tuple[str, Paragraph]]:
        for i, paragraph in enumerate(self.paragraphs, start=1):
            yield f"paragraph{i}", paragraph

    def body_text(self) -> str:
        return "\n\n".join(p.text for p in self.paragraphs)

    def word_count(self) -> int:
        return len(self.body_text().split())
