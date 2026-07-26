"""The blog-derived evidence corpus: `data/evidence.json`.

A blog contains narrative, not skeleton (PLAN.md §2) — no employers, titles, dates or
degree — so it can never be the résumé's source of truth. It is an evidence *layer*: it
lets a bullet say something specific about how a thing was built, with a citation, when
profile.yaml only records that it was built.

Written by `resume-fill blog sync` (M6). Read here by the tailor and the grounding gate,
both of which treat an absent corpus as normal rather than as an error.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from .source import Source, SourceIndex
from .textutil import truncate


class EvidenceItem(BaseModel):
    id: str  # "blog:<slug>#<n>"
    title: str = ""
    url: str = ""
    date: str = ""
    text: str


class Corpus(BaseModel):
    blog_url: str = ""
    generated_at: str = ""
    items: list[EvidenceItem] = Field(default_factory=list)

    def sources(self) -> SourceIndex:
        return {
            item.id: Source(
                id=item.id,
                kind="evidence",
                text=item.text,
                label=f"{item.title or 'blog'} ({item.date})" if item.date else (item.title or "blog"),
            )
            for item in self.items
        }


def load(path: Path) -> Corpus:
    """An empty corpus is a normal state: the tool works without a blog."""
    if not path.exists():
        return Corpus()
    try:
        return Corpus.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # A corrupt cache must not break generation — it is derived data, re-derivable
        # with `blog sync`.
        return Corpus()


def save(corpus: Corpus, path: Path) -> None:
    corpus.generated_at = datetime.now(UTC).isoformat(timespec="seconds")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(corpus.model_dump_json(indent=2), encoding="utf-8")


def catalogue(corpus: Corpus, limit: int = 60, chars: int = 400) -> str:
    """The corpus as prompt text. Truncated: a blog is unbounded and a context window is not."""
    lines = []
    for item in corpus.items[:limit]:
        lines.append(f"- [{item.id}] {item.title}: {truncate(item.text, chars)}")
    return "\n".join(lines)
