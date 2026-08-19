"""The cover letter: same evidence, same gate, different shape.

M5 is cheap because M2 and M3 exist (PLAN.md §8). The letter reuses the source catalogue,
the grounding rules and the renderer; all that is new is a prompt and a template.

That reuse is the point. A cover letter is where invention is most tempting — it is prose,
it is expected to be enthusiastic, and nobody expects it to be checkable. Running it
through the same gate as the résumé is what stops "passionate about distributed systems"
becoming "built distributed systems".
"""

from __future__ import annotations

from pydantic import ValidationError

from .config import Settings
from .document import CoverLetter
from .evidence import Corpus
from .jd import JobDescription
from .lexicon import technical_tokens
from .llm import LLMCall, LLMError
from .profile import Profile
from .tailor import catalogue
from .textutil import truncate

_SYSTEM = """You write cover letters under a hard verification step.

A validator re-reads every paragraph and rejects the letter if a claim cannot be traced to \
the source catalogue you were given: every paragraph cites source ids, every number appears \
in the cited source, every technology appears there or in DECLARED SKILLS.

Enthusiasm is not evidence. "Passionate about distributed systems" is fine; "built \
distributed systems" is a claim and needs a source. If the posting wants something the \
catalogue does not contain, say nothing about it rather than implying it.

Return only JSON."""

_SCHEMA = """{
  "addressee": "who it is addressed to",
  "paragraphs": [{"text": "...", "source_ids": ["exp-....h1"]}],
  "signoff": "Sincerely,"
}"""

_USER = """Write a cover letter for this posting, using only the catalogue below.

=== THE POSTING ===
Title: {title}
Company: {company}
{requirements}

=== SOURCE CATALOGUE (the only facts you may use) ===
{catalogue}

=== RULES ===
1. {paragraph_count} paragraphs, about {words} words in total. Shorter is better than padded.
2. Every paragraph lists the source ids behind it. Cite the narrowest id that supports it.
3. THE FIRST SENTENCE. This is where letters are lost: the most common opening in the pile
   says nothing and announces that it came from a template. Open with something you built
   or did that bears on this role, naming the technologies, and let the role follow from it.
   A reader who finishes the first sentence should know what you work on and in what.

   Never open with any of these, or anything shaped like them:
     "I am writing to..."            "I am excited/thrilled to apply..."
     "I would like to apply..."      "Please accept this application..."
     "As a passionate/dedicated..."  "With great interest..."
     "Re: X", "Subject: X", "Application for X"
   The letter has no subject line by design, and one written into the prose reads as a form.
4. The middle paragraph(s) answer this posting's specific requirements with specific, cited
   work — what the problem was, what you did, how it came out.
5. Numbers: only figures that appear in the cited source. Technologies: only ones named in
   the cited source or in DECLARED SKILLS. Every specific you can use is therefore already
   true, which is the reason to use them: a letter with no figure and no tool in it is a
   form letter with a company name substituted in.
6. Do not restate the job advert back to the reader — they wrote it — and do not praise the
   company. Praise is unverifiable, costs words, and appears in every other letter in the
   pile, so it cannot distinguish this one.
7. Write it the way you would say it out loud. Two lists, for two different reasons.
   Words a model measurably over-produces and almost nobody says: delve, tapestry,
   underscores, showcasing, meticulous, intricate, garnered, realm, pivotal, multifaceted,
   groundbreaking, unparalleled, transformative, invaluable, commendable, noteworthy,
   "testament to", "navigate the complexities". And business clichés, which predate all of
   this and are simply empty: synergy, "game-changer", "hit the ground running",
   "think outside the box", "wear many hats", "a proven track record of success",
   "cutting-edge solutions", "wealth of experience", "in today's fast-paced",
   "ever-evolving", "align perfectly with".
8. Do not open every paragraph with "I".
9. Address it to {addressee}.
10. Tone: {tone}

=== OUTPUT ===
Return JSON exactly in this shape:
{schema}
{feedback}"""


def addressee_for(jd: JobDescription, cfg: Settings) -> str:
    """PLAN.md open question 4: what to do when the addressee is unknown.

    Nothing in a job posting reliably names one, and guessing a person's name from a
    company page is how a letter ends up addressed to someone who left. So: the configured
    fallback, which is a real convention rather than a fake personalisation.
    """
    return cfg.COVER_LETTER_FALLBACK_ADDRESSEE


def paragraph_budget(words: int) -> int:
    """Roughly 75 words a paragraph, floored at three and capped at four.

    Three is the shortest thing that is still a letter — an opening, a middle and a close.
    Four is Yale's ceiling, which is the most specific source there is ("three to four
    paragraphs", with the intro and close at one to three sentences each). UNC says three to
    five and MIT's structure yields four to five, so five is the union of the sources rather
    than their consensus.
    """
    return max(3, min(4, round(words / 75)))


def build_prompt(
    profile: Profile,
    jd: JobDescription,
    corpus: Corpus | None,
    cfg: Settings,
    *,
    feedback: str = "",
) -> tuple[str, str]:
    requirements = ""
    if jd.qualifications:
        requirements = "Qualifications:\n" + "\n".join(f"  - {q}" for q in jd.qualifications[:15])
    if jd.hard_skills:
        requirements += "\nHard skills asked for: " + ", ".join(jd.hard_skills[:30])

    user = _USER.format(
        title=jd.title or "not stated",
        company=jd.company or "not stated",
        requirements=truncate(requirements, 4000),
        catalogue=catalogue(profile, corpus),
        paragraph_count=paragraph_budget(cfg.COVER_LETTER_WORDS),
        words=cfg.COVER_LETTER_WORDS,
        addressee=addressee_for(jd, cfg),
        tone=cfg.COVER_LETTER_TONE,
        schema=_SCHEMA,
        feedback=f"\n=== WHY THE LAST ATTEMPT WAS REJECTED ===\n{feedback}\n" if feedback else "",
    )
    return _SYSTEM, user


def allowed_terms(jd: JobDescription) -> list[str]:
    """Names from the posting that the letter may use without citing anything.

    Naming the company you are writing to is not a claim about yourself. Without this,
    applying to DeepMind or to a team called ScaleKit fails every draft, because a
    CamelCase company name is indistinguishable from a CamelCase product name.
    """
    return technical_tokens(f"{jd.company} {jd.title}")


def write(
    profile: Profile,
    jd: JobDescription,
    corpus: Corpus | None,
    cfg: Settings,
    llm_call: LLMCall,
    *,
    feedback: str = "",
) -> CoverLetter:
    system, user = build_prompt(profile, jd, corpus, cfg, feedback=feedback)
    data = llm_call(system, user)
    try:
        letter = CoverLetter.model_validate(data)
    except ValidationError as exc:
        raise LLMError(f"the model returned a cover letter that does not fit the schema:\n{exc}") from exc
    if not letter.addressee.strip():
        letter.addressee = addressee_for(jd, cfg)
    return letter
