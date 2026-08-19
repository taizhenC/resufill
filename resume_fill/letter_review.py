"""What is wrong with a cover letter, checked mechanically.

ground.py already answers "is any of this false?". This answers the other question, which
is the one that actually gets letters thrown away: **is any of this worth reading?**

Three things this is built on, and the third one is not what it first looks like:

  1. A letter is read, often before the résumé, and a bad one disqualifies a candidate the
     résumé would have got through. So the letter is not decoration.
  2. The opening sentence is where it is lost. "I am writing to express my interest in the
     X position" says nothing and signals a template, which is the specific thing a reader
     is scanning for. HBR, Cornell and Harvard name it independently. (Princeton prints it
     in its own "best" example, so this is a strong majority rather than unanimity.)
  3. Readers *report* recognising machine-written applications and report reacting badly.
     **What they cannot actually do is detect it.** The only controlled measurements put
     humans at 50–52% on exactly this task — chance — including 51.6% in a professional
     self-presentation condition with incentives (Jakesch, Hancock & Naaman, PNAS 120(11),
     n=4,600 across six experiments); a later side-by-side study got 55.4% and found people
     "made the most errors precisely when they were most certain".

So the vocabulary checks below are **not** here because a reader will catch the model. They
are here because the phrases are empty, unverifiable, and in every other letter in the pile,
which makes them worth cutting for a reader who has never thought about AI at all. That is a
weaker claim than "you will be caught" and it is the one the evidence supports.

The prompt in cover.py already asks for all of this. A prompt is a request; this is the
check. That distinction is the same one ground.py rests on, and it exists for the same
reason: the model complies most of the time, and "most of the time" is not a guarantee.

What is deliberately not checked: tone, warmth, "passion", or anything else that would
require an opinion about the candidate rather than a fact about the text. A letter that
fails nothing here can still be a bad letter — this catches the failures that are *legible*,
which is a smaller claim and a true one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .document import CoverLetter
from .jd import JobDescription
from .lexicon import technical_tokens
from .profile import Profile
from .textutil import contains_term, normalize, numbers

# Openings that tell the reader nothing and signal a template in the same breath. The first
# sentence is the most valuable real estate in the letter and these spend it announcing that
# a letter is being sent, which the reader had worked out.
DEAD_OPENINGS = re.compile(
    r"^\s*(?:"
    r"i am writing (?:to|in|because|regarding)|"
    r"i'?m writing (?:to|in|because|regarding)|"
    r"i (?:am|'m) (?:very |extremely |incredibly )?(?:excited|thrilled|delighted|pleased|eager) to (?:apply|submit|express)|"
    r"i would like to (?:apply|express|submit)|"
    r"i wish to apply|"
    r"please accept (?:this|my)|"
    r"as a (?:passionate|dedicated|highly motivated|results[- ]driven|detail[- ]oriented)|"
    r"with (?:great|keen|much) (?:interest|enthusiasm)|"
    r"it is with (?:great|much)|"
    r"re\s*:|subject\s*:|application for\b"
    r")",
    re.I,
)

# The addressee convention that reads as "I did not look". A configured fallback is a real
# convention; this is the one everybody has been told to stop using.
DEAD_ADDRESSEES = re.compile(r"to whom it may concern|dear sir(?: or madam)?|dear madam", re.I)

# Vocabulary an LLM measurably over-produces, from the one empirical corpus there is: Kobak
# et al., Science Advances 2025, which compared 15M biomedical abstracts before and after
# LLMs and annotated 407 excess style words with frequency ratios. The entries here are the
# high-ratio, low-base-rate tail — "delve" at 47.8x, "underscores" and "showcasing" at 13.8x,
# "meticulously" 10.5x, "intricate" 7.4x.
#
# Short on purpose, and the reason is in that 407. Most of the full list is ordinary English
# — it contains "across", "both", "this", "were", "while", "including" — so matching against
# all of it would flag normal prose. A false positive here costs an iteration.
#
# What is deliberately NOT here: "thrilled", "passionate", "excited", "proven". They are the
# register a cover letter is written in, and the corpus shows no excess for any of them
# (0.00x, 0.80x, 1.04x, 0.95x). Banning them would be styling on a hunch. The *opening*
# "I am excited to apply" is caught above, and for a different and better reason.
LLM_EXCESS = (
    "delve", "delving", "delves", "tapestry", "underscores", "underscoring", "showcasing",
    "meticulous", "meticulously", "intricate", "garnered", "realm", "pivotal",
    "multifaceted", "groundbreaking", "unparalleled", "transformative", "invaluable",
    "commendable", "noteworthy", "testament to", "navigate the complexities",
    "seamlessly integrate", "leveraging my",
)

# Business clichés. These are NOT AI tells — every one of them predates LLMs by decades, and
# calling them evidence of a model would be a claim nothing supports. They are here for a
# plainer reason: they are empty, and a reader has seen each of them a hundred times.
BUSINESS_CLICHE = (
    "synergy", "synergies", "game-changer", "hit the ground running",
    "think outside the box", "wear many hats", "a proven track record of success",
    "cutting-edge solutions", "wealth of experience", "robust solutions",
    "unwavering commitment", "in today's fast-paced", "ever-evolving",
    "in the ever-changing", "i am confident that my skills", "align perfectly with",
    "aligns perfectly with", "i am particularly drawn to",
)

# Praise aimed at the employer. Unverifiable, and it spends the letter's words on the
# reader's own organisation. HBR's advice is "don't go overboard with the flattery"; nobody
# has measured what it actually costs a candidate, so this stays advisory. Several of these
# — renowned, esteemed, prestigious — are separately catalogued as the promotional register
# typical of machine-written text, so they sit in two categories at once.
FLATTERY = (
    "industry leader", "leading provider", "world-class", "i have long admired",
    "i have always admired", "your innovative", "your impressive", "your renowned",
    "esteemed", "prestigious", "your amazing", "your incredible",
)

# Two different numbers, and they are not the same thing.
#
# The TARGET, which the prompt asks for: 250-400 words. Princeton says 250-400; Anthropic's
# own application form says "great answers are often 200-400 words"; Harvard converges. HBR
# goes further — "brief enough that someone can read it at a glance" — and the timing data
# (84% of readers spend under a minute) puts 400 at the ceiling of what actually gets read.
#
# The BAND, which the check tolerates. It is deliberately wider at the bottom, because a
# check exists to catch clear problems and spending a model call to grow a tight 230-word
# letter would be optimising the metric rather than the letter. No source states a minimum at
# all, so the floor is a house judgement about whether the letter has said anything — and it
# is labelled as one wherever the user sees it.
TARGET_WORDS = (250, 400)
MIN_WORDS = 200
MAX_WORDS = 400
# Yale is the most specific source and says three to four paragraphs. UNC says 3-5 and MIT's
# structure yields 4-5, so 3-5 is the union of the sources and 3-4 is the consensus.
MIN_PARAGRAPHS = 3
MAX_PARAGRAPHS = 4


@dataclass
class LetterCheck:
    name: str
    ok: bool
    detail: str
    # "blocking" is worth a retry: the letter has a defect a rewrite reliably fixes.
    # "advisory" is worth saying and not worth a model call.
    kind: str = "blocking"
    fix: str = ""

    @property
    def blocking(self) -> bool:
        return self.kind == "blocking"


@dataclass
class LetterReview:
    checks: list[LetterCheck] = field(default_factory=list)

    @property
    def failed(self) -> list[LetterCheck]:
        return [c for c in self.checks if not c.ok]

    @property
    def blocking_failures(self) -> list[LetterCheck]:
        return [c for c in self.failed if c.blocking]

    @property
    def ok(self) -> bool:
        return not self.blocking_failures

    def summary(self) -> str:
        passed = sum(1 for c in self.checks if c.ok)
        return f"{passed} of {len(self.checks)} letter checks passed"

    def as_dict(self) -> list[dict]:
        return [
            {"name": c.name, "ok": c.ok, "detail": c.detail, "kind": c.kind, "fix": c.fix}
            for c in self.checks
        ]


def _phrases_in(text: str, phrases: tuple[str, ...]) -> list[str]:
    low = normalize(text)
    return [p for p in phrases if normalize(p) in low]


def check_opening(letter: CoverLetter) -> LetterCheck:
    first = letter.paragraphs[0].text.strip() if letter.paragraphs else ""
    dead = bool(DEAD_OPENINGS.match(first))
    return LetterCheck(
        "opens on something that happened",
        not dead and bool(first),
        "the first sentence leads with work" if not dead and first
        else f"the letter opens on a formula: {first[:60]!r}" if dead else "there is no first paragraph",
        fix="Open with what you built or did that bears on this role, naming the "
            "technologies. The reader knows a letter is being sent; the first sentence is "
            "the most valuable one on the page and announcing the application spends it.",
    )


def check_addressee(letter: CoverLetter) -> LetterCheck:
    dead = bool(DEAD_ADDRESSEES.search(letter.addressee or ""))
    return LetterCheck(
        "addressee is a convention, not a shrug",
        not dead,
        "addressed to a person or a role" if not dead
        else f"{letter.addressee!r} reads as 'I did not look'",
        fix='Use "Hiring Manager" or the team name. Guessing a name off a company page is '
            "how a letter ends up addressed to somebody who left.",
    )


def check_length(letter: CoverLetter) -> LetterCheck:
    count = letter.word_count()
    ok = MIN_WORDS <= count <= MAX_WORDS
    return LetterCheck(
        "fits on a page and says something",
        ok,
        f"{count} words"
        + ("" if ok else f", outside the {MIN_WORDS}-{MAX_WORDS} band"),
        fix=f"Aim for {TARGET_WORDS[0]}-{TARGET_WORDS[1]} words (Princeton's number, and roughly "
            f"Anthropic's own application form). The {MIN_WORDS}-word floor this check uses is "
            "looser and is a house judgement — no source states a minimum. The ceiling is not: "
            "past 400 it stops being read, which is worse than not sending one.",
    )


def check_shape(letter: CoverLetter) -> LetterCheck:
    count = len(letter.paragraphs)
    ok = MIN_PARAGRAPHS <= count <= MAX_PARAGRAPHS
    return LetterCheck(
        "has an opening, a middle and a close",
        ok,
        f"{count} paragraph(s)" + ("" if ok else f", outside {MIN_PARAGRAPHS}-{MAX_PARAGRAPHS}"),
        fix="Three paragraphs is the shortest thing that is still a letter; past five it is "
            "an essay.",
    )


def check_specifics(letter: CoverLetter) -> LetterCheck:
    """A letter with no figure and no technology in it is a form letter with a company name
    substituted in. The grounding gate guarantees every specific is real, which makes them
    free to insist on."""
    body = letter.body_text()
    figures, tools = numbers(body), technical_tokens(body)
    ok = bool(figures) or len(tools) >= 2
    return LetterCheck(
        "carries specifics",
        ok,
        f"{len(figures)} figure(s) and {len(tools)} named technolog(y/ies)",
        fix="Cite a highlight with a number in it, or name the tools. The gate will not let "
            "a figure be invented, so anything you can say here is already true — the only "
            "reason to leave it out is that a vaguer sentence was easier to write.",
    )


def check_answers_the_posting(letter: CoverLetter, jd: JobDescription) -> LetterCheck:
    """The middle of the letter is supposed to answer this posting. If none of what the
    posting asked for appears anywhere in it, the letter would read the same sent anywhere."""
    wanted = list(dict.fromkeys([*jd.hard_skills, *jd.keywords]))[:30]
    if not wanted:
        return LetterCheck(
            "answers this posting", True, "the posting names nothing specific to answer",
        )
    body = letter.body_text()
    hits = [term for term in wanted if contains_term(body, term)]
    return LetterCheck(
        "answers this posting",
        bool(hits),
        f"{len(hits)} of the posting's terms appear: {', '.join(hits[:6])}" if hits
        else "nothing the posting asked for appears in the letter",
        fix="Answer the posting's requirements with cited work. If the record genuinely "
            "supports none of them, that is the report's gap list and not something to "
            "write around.",
    )


def check_ai_tells(letter: CoverLetter) -> LetterCheck:
    found = _phrases_in(letter.body_text(), LLM_EXCESS)
    return LetterCheck(
        "no vocabulary a model over-produces",
        not found,
        "none found" if not found else f"found: {', '.join(found)}",
        kind="advisory",
        fix="Say it the way you would say it out loud. Not because a reader will catch the "
            "model — the controlled measurements put people at chance on that — but because "
            "these are words almost nobody uses in speech, and a sentence that needs one is "
            "usually a sentence with nothing in it.",
    )


def check_cliches(letter: CoverLetter) -> LetterCheck:
    found = _phrases_in(letter.body_text(), BUSINESS_CLICHE)
    return LetterCheck(
        "no business clichés",
        not found,
        "none found" if not found else f"found: {', '.join(found)}",
        kind="advisory",
        fix="Cut them. They predate LLMs by decades — this is not a claim about how the "
            "letter was written — and a reader has seen each of them a hundred times, which "
            "is exactly why they cannot distinguish this letter from any other.",
    )


def check_names_the_company(letter: CoverLetter, jd: JobDescription) -> LetterCheck:
    """Does the letter say who it is to?

    The opposite failure — naming the *wrong* company, the classic disaster — is already
    impossible here: a company name is a CamelCase token, and ground.check_letter rejects any
    that is not in the allowlist derived from this posting. So the only half left to check is
    the positive one, and it is the half a form letter fails.
    """
    if not jd.company:
        return LetterCheck("names the company", True, "the posting does not name one",
                           kind="advisory")
    named = contains_term(letter.body_text(), jd.company)
    return LetterCheck(
        "names the company",
        named,
        f"{jd.company} appears" if named else f"{jd.company} is never mentioned",
        kind="advisory",
        fix="Say who it is to, once, where it does some work — attached to the thing about "
            "the role you are actually answering, not as a compliment.",
    )


def check_flattery(letter: CoverLetter) -> LetterCheck:
    found = _phrases_in(letter.body_text(), FLATTERY)
    return LetterCheck(
        "no praise aimed at the employer",
        not found,
        "none found" if not found else f"found: {', '.join(found)}",
        kind="advisory",
        fix="Cut it. It is unverifiable, it costs words, and every other letter in the pile "
            "has the same sentence in it — so it cannot distinguish this one.",
    )


def check_i_openings(letter: CoverLetter) -> LetterCheck:
    """Every paragraph starting "I" turns a letter into a list of assertions about the
    writer. One or two is how English works; all of them is a rhythm the reader notices.

    Nobody publishes a threshold for this. It is a house heuristic, it is advisory, and it
    does not belong in the same sentence as anything a parser vendor documents.
    """
    if len(letter.paragraphs) < 3:
        return LetterCheck("varies how the paragraphs open", True, "too few paragraphs to judge",
                           kind="advisory")
    starts = sum(1 for p in letter.paragraphs if re.match(r"^\s*I\b", p.text))
    share = starts / len(letter.paragraphs)
    return LetterCheck(
        "varies how the paragraphs open",
        share < 0.75,
        f"{starts} of {len(letter.paragraphs)} paragraphs open on \"I\"",
        kind="advisory",
        fix="Lead a paragraph with the work rather than the pronoun.",
    )


def check_not_the_advert(letter: CoverLetter, jd: JobDescription) -> LetterCheck:
    """Restating the posting back at the person who wrote it. Checked as overlap with the
    posting's own qualification wording, because that is the text a letter plagiarises when
    it has nothing to say."""
    if not jd.qualifications:
        return LetterCheck("does not restate the advert", True, "the posting lists no qualifications",
                           kind="advisory")
    body = normalize(letter.body_text())
    echoed = [q for q in jd.qualifications if len(q) > 25 and normalize(q) in body]
    return LetterCheck(
        "does not restate the advert",
        not echoed,
        "none of the posting's own sentences appear verbatim" if not echoed
        else f"{len(echoed)} of the posting's sentences appear verbatim",
        kind="advisory",
        fix="The reader wrote the advert. Answer it with your own work instead of quoting it.",
    )


def review(letter: CoverLetter, jd: JobDescription, profile: Profile | None = None) -> LetterReview:
    return LetterReview(checks=[
        check_opening(letter),
        check_addressee(letter),
        check_length(letter),
        check_shape(letter),
        check_specifics(letter),
        check_answers_the_posting(letter, jd),
        check_names_the_company(letter, jd),
        check_ai_tells(letter),
        check_cliches(letter),
        check_flattery(letter),
        check_i_openings(letter),
        check_not_the_advert(letter, jd),
    ])


def feedback(result: LetterReview) -> str:
    """What the writer is told on a retry. Blocking failures first, because those are the
    reason there is a retry at all."""
    failures = result.blocking_failures + [c for c in result.failed if not c.blocking]
    if not failures:
        return ""
    lines = ["The letter is truthful but reads poorly. Fix these, keeping every citation:"]
    for check in failures:
        lines.append(f"  - {check.name}: {check.detail}")
        if check.fix:
            lines.append(f"    {check.fix}")
    return "\n".join(lines)
