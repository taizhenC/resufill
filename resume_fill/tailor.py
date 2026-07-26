"""Selection and phrasing — the only stage where a model writes anything.

What it is allowed to decide: which recorded entries appear, in what order, and how each
one is phrased for this particular posting. What it is not allowed to decide: employers,
titles, dates, or the existence of anything. Those are copied from profile.yaml by id
downstream, so they cannot be generated and therefore cannot be wrong.

The prompt states the grounding rules, but the prompt is not the enforcement — ground.py
is. The rules are stated here only so the first attempt usually passes.
"""

from __future__ import annotations

from pydantic import ValidationError

from .document import ResumeDoc
from .evidence import Corpus
from .evidence import catalogue as evidence_catalogue
from .jd import JobDescription
from .llm import LLMCall, LLMError
from .profile import Profile
from .textutil import truncate

_SYSTEM = """You are a résumé writer working under a hard verification step.

A validator re-reads everything you write and rejects the document if any claim cannot be \
traced to the source catalogue you were given. It checks, mechanically:

  - every bullet cites at least one source id that exists;
  - every number in a bullet appears in the cited source;
  - every technology named in a bullet appears in the cited source or in DECLARED SKILLS.

So: rephrase freely, select aggressively, and never add a fact. If the posting wants \
something the catalogue does not contain, leave it out. The report tells the candidate it \
is missing, which is useful; a fabricated version of it is not.

Return only JSON."""

_SCHEMA = """{
  "headline": "one line under the name, or \\"\\"",
  "summary": "2-3 sentences, or \\"\\" if there is nothing specific to say",
  "summary_source_ids": ["id", ...],
  "experience": [{"source_id": "exp-...", "bullets": [{"text": "...", "source_ids": ["exp-....h1"]}]}],
  "projects":   [{"source_id": "proj-...", "bullets": [{"text": "...", "source_ids": ["proj-....h1"]}]}],
  "education":  [{"source_id": "edu-...", "bullets": [{"text": "...", "source_ids": ["edu-....h1"]}]}],
  "certification_ids": ["cert-..."],
  "skills": {"Languages": ["..."], "Tools": ["..."]},
  "section_order": ["summary", "skills", "experience", "projects", "education", "certifications"]
}"""

_USER = """Write a résumé for this posting, using only the catalogue below.

=== THE POSTING ===
{jd_block}

=== SOURCE CATALOGUE (the only facts you may use) ===
{catalogue}

=== RULES ===
1. Select entries by their id. Do not write company names, job titles or dates anywhere —
   they are filled in from the record automatically.
2. Every bullet must list the source ids it came from. Cite the narrowest id that supports
   it (a highlight id, not the whole entry) so the citation means something.
3. Numbers: only figures that appear in the cited source. Never round, restate or infer one.
4. Technologies: only ones named in the cited source, or listed in DECLARED SKILLS.
5. The skills block must be a subset of DECLARED SKILLS. Reorder and trim it for this
   posting — that is the whole point — but add nothing.
6. Lead each bullet with what was done and how it turned out. Prefer the entries and
   bullets that answer this posting's requirements; drop the ones that do not.
7. Budget: about {bullet_budget} bullets in total across all sections, so it fits
   {max_pages} page(s). Fewer, sharper bullets beat more.
{extra_rules}
=== OUTPUT ===
Return JSON exactly in this shape:
{schema}
{feedback}"""


def _jd_block(jd: JobDescription) -> str:
    parts = [f"Title: {jd.title or 'not stated'}", f"Company: {jd.company or 'not stated'}"]
    if jd.seniority:
        parts.append(f"Seniority: {jd.seniority}")
    if jd.min_years is not None:
        parts.append(f"Stated experience: {jd.min_years}+ years")
    if jd.hard_skills:
        parts.append("Hard skills asked for: " + ", ".join(jd.hard_skills[:40]))
    if jd.qualifications:
        parts.append("Qualifications:\n" + "\n".join(f"  - {q}" for q in jd.qualifications[:20]))
    if jd.responsibilities:
        parts.append("Responsibilities:\n" + "\n".join(f"  - {r}" for r in jd.responsibilities[:15]))
    return "\n".join(parts)


def catalogue(profile: Profile, corpus: Corpus | None = None) -> str:
    """Every id the tailor may cite, with what that id actually says.

    Written as a flat, id-first list because the model has to copy those ids back verbatim,
    and anything it has to reconstruct it will eventually reconstruct wrong.
    """
    lines: list[str] = []

    def entry_block(entry, header: str) -> None:
        lines.append(f"[{entry.id}] {header}")
        if getattr(entry, "summary", ""):
            lines.append(f"    context: {entry.summary}")
        for highlight in entry.highlights:
            skills = f"  (skills: {', '.join(highlight.skills)})" if highlight.skills else ""
            lines.append(f"    [{highlight.id}] {highlight.text}{skills}")

    if profile.experience:
        lines.append("EXPERIENCE")
        for exp in profile.sorted_experience():
            entry_block(exp, f"{exp.company} — {exp.title} — {exp.location} — {exp.dates}")
    if profile.projects:
        lines.append("\nPROJECTS")
        for proj in profile.sorted_projects():
            entry_block(proj, f"{proj.name} — {proj.dates}")
    if profile.education:
        lines.append("\nEDUCATION")
        for edu in profile.sorted_education():
            entry_block(edu, f"{edu.institution} — {edu.label} — {edu.dates}")
    if profile.certifications:
        lines.append("\nCERTIFICATIONS")
        lines.extend(f"[{c.id}] {c.label} — {c.date}" for c in profile.certifications)

    lines.append("\nDECLARED SKILLS (assertable without a bullet citing them)")
    lines.append(", ".join(profile.all_skills()) or "(none)")

    if corpus and corpus.items:
        lines.append("\nBLOG EVIDENCE (narrative only — it has no dates or employers; cite it to")
        lines.append("add specifics to a bullet, never as an entry of its own)")
        lines.append(evidence_catalogue(corpus))
    return "\n".join(lines)


def bullet_budget(max_pages: int) -> int:
    """A page of single-column 10.5pt text holds roughly this many résumé bullets once the
    header, section rules and entry headers have taken their share."""
    return max(6, 14 * max(1, max_pages))


def build_prompt(
    profile: Profile,
    jd: JobDescription,
    corpus: Corpus | None,
    *,
    max_pages: int = 1,
    feedback: str = "",
    extra_rules: str = "",
) -> tuple[str, str]:
    user = _USER.format(
        jd_block=truncate(_jd_block(jd), 8000),
        catalogue=catalogue(profile, corpus),
        bullet_budget=bullet_budget(max_pages),
        max_pages=max_pages,
        schema=_SCHEMA,
        extra_rules=(extra_rules + "\n") if extra_rules else "",
        feedback=f"\n=== WHY THE LAST ATTEMPT WAS REJECTED ===\n{feedback}\n" if feedback else "",
    )
    return _SYSTEM, user


def tailor(
    profile: Profile,
    jd: JobDescription,
    corpus: Corpus | None,
    llm_call: LLMCall,
    *,
    max_pages: int = 1,
    feedback: str = "",
    extra_rules: str = "",
) -> ResumeDoc:
    system, user = build_prompt(
        profile, jd, corpus, max_pages=max_pages, feedback=feedback, extra_rules=extra_rules
    )
    data = llm_call(system, user)
    try:
        doc = ResumeDoc.model_validate(data)
    except ValidationError as exc:
        # A malformed document is not a grounding failure and cannot be fed back as one —
        # the loop would spend its whole budget re-litigating a JSON shape.
        raise LLMError(f"the model returned a résumé document that does not fit the schema:\n{exc}") from exc
    if not (doc.experience or doc.projects or doc.education):
        # Every field on ResumeDoc has a default, so an unrelated JSON object validates
        # cleanly into an empty document. Without this check a garbage response becomes a
        # résumé with a name and nothing else, and grounding passes it — there is nothing
        # in it to be wrong.
        raise LLMError(
            "the model returned a résumé with no entries selected. Response keys: "
            f"{sorted(data)[:10]}"
        )
    return doc
