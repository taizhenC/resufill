"""The local proxy score, and the gap list that is the actually useful output.

Read PLAN.md §2 before trusting this number. **No employer computes it.** Greenhouse and
Lever do not rank by keyword at all — they parse a résumé into fields for recruiter search.
Taleo and iCIMS do keyword search, recruiter-side. Jobscan-style "match scores" are vendor
heuristics with no standing anywhere. So this is a stopping rule for the auto-iterate loop
and a way to see what a posting asked for that the record cannot answer. It is not a
prediction about anything.

Every component is therefore printed as a breakdown with its own explanation, never as a
bare number, and the weights are the ones written down in PLAN.md §4 rather than tuned
until the output looked good.

The score is only honest because ground.py exists. A loop optimising keyword coverage has
one cheap way to raise its number — invent keywords — and the gate is what removes it.
That makes the ceiling meaningful: a low score means the role genuinely wants things you
have not done.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import ats
from .ats import AtsReport, Check
from .document import ResumeDoc
from .jd import JobDescription
from .lexicon import canonical, find_terms
from .profile import Profile
from .source import SourceIndex
from .textutil import contains_term, normalize, words
from .verify import VerifyReport

# PLAN.md §4. Not tuned.
WEIGHTS = {
    "hard_skills": 0.40,
    "qualifications": 0.15,
    "title_fit": 0.15,
    "keywords_in_context": 0.20,
    "format": 0.10,
}

# Words that carry no signal when deciding whether a qualification is addressed.
_STOPWORDS = {
    "a", "an", "and", "or", "the", "to", "of", "in", "on", "at", "for", "with", "by", "from",
    "as", "is", "are", "be", "been", "being", "have", "has", "had", "will", "would", "can",
    "could", "should", "must", "may", "you", "your", "we", "our", "us", "they", "their", "it",
    "this", "that", "these", "those", "experience", "years", "year", "strong", "excellent",
    "good", "great", "solid", "ability", "able", "work", "working", "knowledge", "familiar",
    "familiarity", "understanding", "proficiency", "proficient", "skills", "skill", "plus",
    "bonus", "nice", "preferred", "required", "requirements", "using", "use", "used", "such",
    "including", "etc", "other", "others", "well", "least", "more", "most", "some", "any",
}


@dataclass
class Component:
    name: str
    label: str
    weight: float
    raw: float  # 0..1
    detail: str

    @property
    def points(self) -> float:
        return self.weight * self.raw * 100


@dataclass
class Gap:
    """Something the posting asked for that the résumé does not say.

    `in_record` is the distinction that makes the list worth reading: a gap that is
    somewhere in profile.yaml but was not surfaced is a tailoring miss you can fix by
    editing the record; a gap that is nowhere in the record is a fact about you, and no
    amount of rewriting will close it.
    """

    keyword: str
    in_record: bool
    where: str = ""


@dataclass
class Score:
    components: list[Component] = field(default_factory=list)
    matched: list[str] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)
    stuffed: list[str] = field(default_factory=list)
    # Kept verbatim rather than only counted: "3 of 11 addressed" tells you nothing about
    # which three, and the wording of the other eight is the useful part.
    unaddressed_qualifications: list[str] = field(default_factory=list)
    # Words from the posting's own job title that the résumé never uses for the role. These
    # are the cheapest points on the page: the headline is phrasing, not a claim, so using
    # the reader's words for the thing you already do costs nothing and is not fabrication.
    title_words_missing: list[str] = field(default_factory=list)

    @property
    def total(self) -> float:
        return round(sum(c.points for c in self.components), 1)

    def component(self, name: str) -> Component:
        return next(c for c in self.components if c.name == name)

    def real_gaps(self) -> list[Gap]:
        return [g for g in self.gaps if not g.in_record]

    def unsurfaced(self) -> list[Gap]:
        return [g for g in self.gaps if g.in_record]


# ------------------------------------------------------------ components ----


def _coverage(terms: list[str], haystack: str) -> tuple[list[str], list[str]]:
    matched, missing = [], []
    for term in terms:
        (matched if contains_term(haystack, term) else missing).append(term)
    return matched, missing


def _content_words(text: str) -> set[str]:
    return {w for w in words(text) if len(w) > 2 and w not in _STOPWORDS}


def addresses(qualification: str, haystack: str) -> bool:
    """Does the résumé answer this qualification?

    Two ways, because postings write them two ways. A qualification naming concrete
    technologies is answered by naming them; one written as prose ("comfortable owning a
    service end to end") is answered by overlapping vocabulary. Neither is precise, which
    is why the report lists the unaddressed ones verbatim instead of only counting them.
    """
    terms = find_terms(qualification)
    if terms:
        hits = sum(1 for t in terms if contains_term(haystack, t))
        return hits * 2 >= len(terms)
    needed = _content_words(qualification)
    if not needed:
        return True
    present = _content_words(haystack)
    return len(needed & present) / len(needed) >= 0.4


def _hard_skills(jd: JobDescription, haystack: str) -> tuple[Component, list[str], list[str]]:
    if not jd.hard_skills:
        return (
            Component("hard_skills", "Hard-skill coverage vs JD", WEIGHTS["hard_skills"], 1.0,
                      "the posting names no specific technologies, so there is nothing to cover"),
            [], [],
        )
    matched, missing = _coverage(jd.hard_skills, haystack)
    raw = len(matched) / len(jd.hard_skills)
    return (
        Component("hard_skills", "Hard-skill coverage vs JD", WEIGHTS["hard_skills"], raw,
                  f"{len(matched)} of {len(jd.hard_skills)} named technologies appear"),
        matched, missing,
    )


def _qualifications(jd: JobDescription, haystack: str) -> tuple[Component, list[str]]:
    if not jd.qualifications:
        return (
            Component("qualifications", "Required qualifications addressed", WEIGHTS["qualifications"],
                      1.0, "the posting lists no qualifications"),
            [],
        )
    unaddressed = [q for q in jd.qualifications if not addresses(q, haystack)]
    raw = 1 - len(unaddressed) / len(jd.qualifications)
    return (
        Component("qualifications", "Required qualifications addressed", WEIGHTS["qualifications"],
                  raw, f"{len(jd.qualifications) - len(unaddressed)} of {len(jd.qualifications)} addressed"),
        unaddressed,
    )


_SENIORITY_WORDS = {
    "intern": r"intern|co-?op",
    "entry": r"intern|junior|associate|assistant|entry",
    "mid": r"engineer|developer|analyst|scientist|designer",
    "senior": r"senior|sr\.?|lead|staff|principal",
    "staff": r"staff|principal|architect|distinguished",
    "lead": r"lead|manager|head|director|principal",
}


def _title_fit(
    jd: JobDescription, doc: ResumeDoc, profile: Profile
) -> tuple[Component, list[str]]:
    """Two halves: does the résumé speak the posting's vocabulary for the role, and does
    the level it demonstrates match the level it asks for?"""
    held_titles = " ".join(
        e.title for e in profile.experience if e.id in {s.source_id for s in doc.experience}
    )
    surface = " ".join([doc.headline, held_titles, profile.basics.headline])
    component = _title_fit_from(jd, surface)
    missing = sorted(_content_words(jd.title) - _content_words(surface)) if jd.title else []
    return component, missing


def _title_fit_from(jd: JobDescription, text: str, *, level_text: str | None = None) -> Component:
    """The two halves measure different kinds of thing, which is why they can be given
    different surfaces.

    Vocabulary is about *phrasing*: the headline is written by the tailor, and a grounded
    headline may name anything the record supports. Level is about *fact*: what a candidate
    demonstrably held. The ceiling passes the whole record for the first and only the held
    titles for the second — see `ceiling`. The scorer passes one surface for both, because
    it is looking at a document that already exists.
    """
    surface = normalize(text)

    if jd.title:
        wanted = _content_words(jd.title)
        overlap = len(wanted & _content_words(surface)) / len(wanted) if wanted else 1.0
    else:
        overlap = 1.0

    if not jd.seniority:
        detail = f"title vocabulary {overlap:.0%} matched; posting states no level"
        return Component("title_fit", "Title / seniority alignment", WEIGHTS["title_fit"], overlap, detail)

    levels = normalize(level_text) if level_text is not None else surface
    pattern = _SENIORITY_WORDS.get(jd.seniority, jd.seniority)
    level = 1.0 if re.search(pattern, levels, re.I) else 0.0
    detail = (
        f"title vocabulary {overlap:.0%} matched; "
        f"{'the record shows' if level else 'nothing in the record shows'} a {jd.seniority}-level role"
    )
    return Component("title_fit", "Title / seniority alignment", WEIGHTS["title_fit"],
                     0.5 * overlap + 0.5 * level, detail)


def _keywords_in_context(jd: JobDescription, doc: ResumeDoc) -> tuple[Component, list[str]]:
    """Coverage measured in the bullets and summary — not the skills list.

    A skills line is free to write and carries no evidence, so counting it here would
    reward exactly the padding this component exists to discourage. Repetition is
    penalised for the same reason.
    """
    context = "\n".join([doc.summary, doc.bullet_text()])
    if not jd.keywords:
        return (
            Component("keywords_in_context", "Keyword presence in context",
                      WEIGHTS["keywords_in_context"], 1.0, "no keywords extracted from the posting"),
            [],
        )
    matched, _ = _coverage(jd.keywords, context)
    coverage = len(matched) / len(jd.keywords)

    bullet_count = max(1, sum(1 for _ in doc.bullets()))
    stuffing_limit = max(3, round(bullet_count * 0.4))
    stuffed = [
        term for term in matched
        if len(re.findall(rf"(?<![a-z0-9]){re.escape(normalize(term))}(?![a-z0-9])", normalize(context)))
        > stuffing_limit
    ]
    penalty = min(0.5, 0.1 * len(stuffed))
    detail = f"{len(matched)} of {len(jd.keywords)} keywords appear inside bullets or the summary"
    if stuffed:
        detail += f"; {len(stuffed)} repeated more than {stuffing_limit} times (penalised)"
    return (
        Component("keywords_in_context", "Keyword presence in context",
                  WEIGHTS["keywords_in_context"], coverage * (1 - penalty), detail),
        stuffed,
    )


def _format(review: AtsReport, verify_report: VerifyReport | None) -> Component:
    """The one component that is not about the posting at all.

    It used to be five hand-rolled booleans about whether a bullet was too long. ats.py now
    owns the rubric — what a parser demonstrably does with the document, and what a human
    reviewer demonstrably does — and this reads it. Same weight (PLAN.md §4, not tuned); a
    great deal more behind the number.
    """
    checks = list(review.checks)
    if verify_report is not None:
        checks.append(
            Check(
                "PDF text extracts cleanly", verify_report.ok,
                verify_report.summary(),
                fix="Look at resume.html next to the PDF: the first question is whether the "
                    "bullet made it into the markup at all.",
            )
        )
    passed = sum(1 for c in checks if c.ok)
    failed = [c.name for c in checks if not c.ok]
    detail = f"{passed} of {len(checks)} checks passed"
    if failed:
        detail += "; failed: " + ", ".join(failed)
    return Component("format", "Format checks passed", WEIGHTS["format"], passed / len(checks), detail)


# ----------------------------------------------------------------- gaps ----


def classify_gaps(missing: list[str], index: SourceIndex) -> list[Gap]:
    """Split the misses into "you have this and it did not get surfaced" and "you do not
    have this". Only the second kind is a fact about you."""
    gaps = []
    for term in missing:
        where = ""
        for source in index.values():
            if contains_term(source.text, term) or any(
                contains_term(skill, term) for skill in source.skills
            ):
                where = source.label
                break
        gaps.append(Gap(keyword=canonical(term), in_record=bool(where), where=where))
    return gaps


def score(
    doc: ResumeDoc,
    profile: Profile,
    jd: JobDescription,
    index: SourceIndex,
    report: VerifyReport | None = None,
    review: AtsReport | None = None,
) -> Score:
    """`review` is passed in when the caller already has one — the pipeline builds it with
    the rendered HTML and the real page count, neither of which is knowable from the
    document alone. Without it the checks that need those are simply not run, which is
    correct: an absent check must never be scored as a passing one."""
    if review is None:
        review = ats.review(
            doc, profile,
            page_count=report.page_count if report else None,
            max_pages=1,
        )
    haystack = doc.searchable_text()
    hard, matched, missing = _hard_skills(jd, haystack)
    quals, unaddressed = _qualifications(jd, haystack)
    keywords, stuffed = _keywords_in_context(jd, doc)

    # Keywords the posting wanted that never appear anywhere in the document, whichever
    # component noticed first.
    _, missing_keywords = _coverage(jd.keywords, haystack)
    all_missing = list(dict.fromkeys(missing + missing_keywords))

    title, missing_title_words = _title_fit(jd, doc, profile)
    return Score(
        components=[hard, quals, title, keywords, _format(review, report)],
        matched=matched,
        gaps=classify_gaps(all_missing, index),
        stuffed=stuffed,
        unaddressed_qualifications=unaddressed,
        title_words_missing=missing_title_words,
    )


# --------------------------------------------------------------- ceiling ----


@dataclass
class Ceiling:
    """The highest this score can go for this record against this posting.

    The number is a stopping rule (PLAN.md §2), and a stopping rule that cannot be reached
    is not a rule, it is a way of spending four LLM calls to arrive at the same answer the
    first one gave. A posting asking for Kubernetes against a record that has never touched
    it caps the hard-skill component before a single word is written — no rewrite closes
    that, because ground.py exists to make sure no rewrite can.

    So the loop is told what is reachable and stops when it gets there, and the report says
    "62.4 of a reachable 64.1" instead of "62.4 against a threshold of 80", which reads as a
    failure and is not one.

    This is computed from the record and the posting alone. It is deliberately optimistic:
    it assumes every keyword the record contains anywhere could be surfaced on one page,
    which a one-page budget will not always allow. An optimistic ceiling is the safe
    direction — it never stops the loop early on the grounds that something was impossible
    when it was merely hard.
    """

    total: float
    components: dict[str, float] = field(default_factory=dict)
    # Keywords the posting asked for that appear nowhere in the record. These are the whole
    # reason the ceiling is below 100, and they are facts about the candidate.
    unreachable: list[str] = field(default_factory=list)

    def covers(self, total: float) -> bool:
        """Is `total` at or under this ceiling?

        Kept as a method with a name rather than an inline comparison, because the *only*
        interesting answer is False: that would mean a real draft scored above what was
        computed as its maximum, and the ceiling would be measuring the wrong thing.
        """
        return total <= self.total + 1e-9

    def gap_to(self, threshold: float) -> float:
        """How far the threshold is above what this record can reach. Zero when reachable."""
        return max(0.0, threshold - self.total)

    def is_reachable(self, threshold: float) -> bool:
        return self.total >= threshold


def record_text(profile: Profile, index: SourceIndex) -> str:
    """Everything the résumé could possibly say, if the page were infinite.

    The union of every source's text and every declared skill — which is exactly the set
    ground.py will license claims from, so a keyword absent from this string is a keyword no
    grounded document can contain.
    """
    parts = [source.text for source in index.values()]
    parts.extend(" ".join(source.skills) for source in index.values())
    parts.extend([profile.basics.headline, " ".join(profile.all_skills())])
    return "\n".join(p for p in parts if p)


def ceiling(profile: Profile, jd: JobDescription, index: SourceIndex) -> Ceiling:
    """The score a perfect selection from this record would get against this posting."""
    haystack = record_text(profile, index)
    raws: dict[str, float] = {}

    if jd.hard_skills:
        matched, missing = _coverage(jd.hard_skills, haystack)
        raws["hard_skills"] = len(matched) / len(jd.hard_skills)
    else:
        raws["hard_skills"] = 1.0
        missing = []

    if jd.qualifications:
        answered = sum(1 for q in jd.qualifications if addresses(q, haystack))
        raws["qualifications"] = answered / len(jd.qualifications)
    else:
        raws["qualifications"] = 1.0

    # The two halves have different ceilings, and conflating them made this number one a
    # real draft could score *above* — which reads as a bug in the report and undermines the
    # only thing the number is for.
    #
    # Vocabulary is always fully reachable. The headline is written by the tailor, and the
    # grounding gate polices technical terms and figures rather than ordinary words, so
    # phrasing a headline in the posting's own words is free and legitimate — it is the
    # tailoring this tool exists to do. Level is not reachable at all if the record does not
    # show it: seniority is a fact about roles held, and no phrasing manufactures one.
    titles = " ".join([*(e.title for e in profile.experience), profile.basics.headline])
    raws["title_fit"] = _title_fit_from(jd, jd.title, level_text=titles).raw

    if jd.keywords:
        matched_kw, missing_kw = _coverage(jd.keywords, haystack)
        raws["keywords_in_context"] = len(matched_kw) / len(jd.keywords)
    else:
        raws["keywords_in_context"] = 1.0
        missing_kw = []

    # Every format check is passable by construction — the renderer produces a single
    # column, and the page budget is a choice rather than a fact about the record.
    raws["format"] = 1.0

    total = round(sum(WEIGHTS[name] * raw * 100 for name, raw in raws.items()), 1)
    unreachable = [canonical(t) for t in dict.fromkeys([*missing, *missing_kw])]
    return Ceiling(total=total, components=raws, unreachable=unreachable)


# ---------------------------------------------------------- loop feedback ----


def feedback(result: Score, threshold: float, report: VerifyReport | None = None) -> str:
    """What the tailor is told when the draft is honest but does not clear the threshold.

    It is pointed at the gaps that *are* in the record, because those are the only ones a
    rewrite can close. Naming the others would be an invitation to invent them, and
    ground.py would reject the result — costing an iteration to learn nothing.
    """
    lines = [
        f"The draft is truthful but scored {result.total:.1f} against a threshold of {threshold:.0f}.",
        "Improve it WITHOUT adding anything the catalogue does not contain.",
    ]
    unsurfaced = result.unsurfaced()
    if unsurfaced:
        lines.append("")
        lines.append("These are in the record but did not make it into the résumé. Surface them by")
        lines.append("selecting or rewriting the bullets that already contain them:")
        lines.extend(f"  - {g.keyword} (in: {g.where})" for g in unsurfaced[:15])
    if result.title_words_missing:
        lines.append("")
        lines.append(
            "The headline does not use the posting's own words for the role. Rewrite it so it "
            "does, as far as the record's substance allows: "
            + ", ".join(result.title_words_missing[:8])
        )
        lines.append(
            "This is phrasing, not a claim — the gate polices technologies and figures, not "
            "which ordinary words describe the same job."
        )
    if result.unaddressed_qualifications:
        lines.append("")
        lines.append("Qualifications the draft does not answer:")
        lines.extend(f"  - {q}" for q in result.unaddressed_qualifications[:10])
    if result.stuffed:
        lines.append("")
        lines.append(
            "Repeated too often - repetition is penalised, not rewarded: "
            + ", ".join(result.stuffed)
        )
    if report is not None and not report.ok:
        lines.append("")
        lines.append("The rendered PDF also failed its checks:")
        lines.extend(f"  - {item}" for item in report.missing[:10])
    real = result.real_gaps()
    if real:
        lines.append("")
        lines.append(
            "Not in the record at all, so LEAVE THEM OUT - they are reported to the "
            "candidate as genuine gaps: " + ", ".join(g.keyword for g in real[:15])
        )
    return "\n".join(lines)
