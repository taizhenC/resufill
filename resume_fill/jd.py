"""Job description -> structured requirements.

Deterministic extraction first, one LLM pass second (PLAN.md §4). The order matters: the
lexicon pass is what lets `gen` parse a posting with no API key configured at all, and it
also means the model can only ever *add* to the requirement set, never quietly drop a skill
the posting plainly asked for.

Input can be a file, stdin, or a posting URL — PLAN.md open question 2, resolved as "all
three", because they cost one function each and picking one would be the only wrong answer.
"""

from __future__ import annotations

import html
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .lexicon import canonical, find_terms
from .llm import LLMCall, LLMError
from .profile import slug
from .textutil import normalize, truncate

_BULLET = re.compile(r"^\s*(?:[-•‣▪·◦*+]|\d+[.)])\s+")
_HEADING = re.compile(r"^\s*([A-Z][\w &/'-]{2,44})\s*:?\s*$")

_REQUIREMENT_HEADINGS = re.compile(
    r"requirement|qualification|what you'?ll need|what we'?re looking for|who you are|"
    r"about you|you have|must have|basic|minimum|preferred|nice to have|bonus|skills",
    re.I,
)
_RESPONSIBILITY_HEADINGS = re.compile(
    r"responsibilit|what you'?ll do|the role|day to day|day-to-day|you will|impact", re.I,
)

_SENIORITY = [
    ("intern", r"\bintern(ship)?\b|\bco-?op\b"),
    ("entry", r"\bentry[- ]level\b|\bnew grad(uate)?\b|\bjunior\b|\bassociate\b|\bI\b(?!\w)"),
    ("mid", r"\bmid[- ]level\b|\bintermediate\b|\bII\b"),
    ("senior", r"\bsenior\b|\bsr\.?\b|\bIII\b"),
    ("staff", r"\bstaff\b|\bprincipal\b|\bdistinguished\b|\barchitect\b"),
    ("lead", r"\blead\b|\bmanager\b|\bhead of\b|\bdirector\b"),
]
_ROLE_WORD = re.compile(
    r"engineer|developer|scientist|analyst|manager|designer|researcher|architect|"
    r"administrator|consultant|specialist|intern|technician|programmer",
    re.I,
)
_LABELLED_TITLE = re.compile(r"^\s*(?:job\s+)?title\s*:\s*(.+)$", re.I | re.M)
_LABELLED_COMPANY = re.compile(r"^\s*company\s*:\s*(.+)$", re.I | re.M)
# "About Northwind" names the company; "About Us" and "About the role" do not.
_ABOUT_COMPANY = re.compile(
    r"^\s*[Aa]bout\s+(?!(?i:the|us|our|this|you|me|role|team|job|position)\b)([A-Z][\w.&' -]{1,40})\s*$",
    re.M,
)
_AT_COMPANY = re.compile(r"\bat\s+([A-Z][\w.&']*(?:\s+[A-Z][\w.&']*){0,2})\b")

# Years-of-experience demands, which are a requirement the résumé can answer or cannot.
_YEARS = re.compile(r"(\d+)\+?\s*(?:-\s*\d+\s*)?years?", re.I)


@dataclass
class JobDescription:
    raw: str
    title: str = ""
    company: str = ""
    seniority: str = ""
    hard_skills: list[str] = field(default_factory=list)
    qualifications: list[str] = field(default_factory=list)
    responsibilities: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    min_years: int | None = None

    @property
    def run_slug(self) -> str:
        """`out/<company>-<role>-<date>/` comes from here, so it has to be filename-safe
        and still recognisable a month later."""
        return "-".join(p for p in (slug(self.company, 24), slug(self.title, 32)) if p and p != "x")

    def summary_line(self) -> str:
        bits = [self.title or "role unknown", self.company or "company unknown"]
        if self.seniority:
            bits.append(self.seniority)
        return " | ".join(bits)


# ------------------------------------------------------------------ input ----


def strip_html(markup: str) -> str:
    """Enough HTML handling to read a posting page. Job boards are div soup; the text is
    all that is wanted and a real parser would be a dependency for one function."""
    text = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", markup)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|li|tr|h[1-6]|section)>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "\n- ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t ]+", " ", text)
    return re.sub(r"\n\s*\n\s*\n+", "\n\n", text).strip()


def read_input(source: str, *, user_agent: str = "resume-fill/0.1") -> str:
    """A path, "-" for stdin, or an https URL."""
    if source == "-":
        return sys.stdin.read()
    if re.match(r"^https?://", source):
        import httpx

        response = httpx.get(
            source, follow_redirects=True, timeout=30.0, headers={"User-Agent": user_agent}
        )
        response.raise_for_status()
        return strip_html(response.text)
    path = Path(source)
    if not path.is_file():
        raise FileNotFoundError(f"no job description at {source} (pass a file, an https URL, or - for stdin)")
    return path.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------- deterministic ----


def _lines(text: str) -> list[str]:
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]


def _grouped_bullets(text: str) -> tuple[list[str], list[str]]:
    """Split the posting's bullet lists into requirements and responsibilities.

    Bullets with no heading above them are filed as requirements: a posting that lists
    demands without labelling them is common, and under-reporting a requirement is the
    more damaging error — it becomes a gap the report never mentions.
    """
    requirements: list[str] = []
    responsibilities: list[str] = []
    bucket = requirements
    for line in _lines(text):
        if _BULLET.match(line):
            item = _BULLET.sub("", line).strip(" .;")
            if len(item) > 3:
                bucket.append(item)
            continue
        heading = _HEADING.match(line)
        candidate = heading.group(1) if heading else line
        if len(candidate) < 80:
            if _RESPONSIBILITY_HEADINGS.search(candidate):
                bucket = responsibilities
            elif _REQUIREMENT_HEADINGS.search(candidate):
                bucket = requirements
    return requirements, responsibilities


def _title(text: str) -> str:
    if match := _LABELLED_TITLE.search(text):
        return match.group(1).strip()
    for line in _lines(text)[:12]:
        if len(line) <= 70 and _ROLE_WORD.search(line) and not _BULLET.match(line):
            return re.sub(r"\s*[-–—|@]\s*.*$", "", line).strip()
    return ""


def _company(text: str) -> str:
    if match := _LABELLED_COMPANY.search(text):
        return match.group(1).strip()
    if match := _ABOUT_COMPANY.search(text):
        return match.group(1).strip()
    head = "\n".join(_lines(text)[:12])
    if match := _AT_COMPANY.search(head):
        return match.group(1).strip()
    return ""


def _seniority(text: str, title: str) -> str:
    # The title is the reliable signal; the body mentions "senior engineers" for other reasons.
    for level, pattern in _SENIORITY:
        if re.search(pattern, title):
            return level
    for level, pattern in _SENIORITY:
        if re.search(pattern, text[:600], re.I):
            return level
    return ""


def _min_years(requirements: list[str]) -> int | None:
    years = [int(m.group(1)) for line in requirements for m in _YEARS.finditer(line)]
    return min(years) if years else None


def parse_deterministic(text: str) -> JobDescription:
    """Everything that can be known without a model. This alone is a usable JobDescription."""
    requirements, responsibilities = _grouped_bullets(text)
    title = _title(text)
    skills = find_terms(text)
    return JobDescription(
        raw=text,
        title=title,
        company=_company(text),
        seniority=_seniority(text, title),
        hard_skills=skills,
        qualifications=requirements,
        responsibilities=responsibilities,
        keywords=list(skills),
        min_years=_min_years(requirements),
    )


# -------------------------------------------------------------- LLM pass ----

_SYSTEM = """You read job postings and return structured JSON. You never invent requirements: \
everything you report must be stated in the posting. If a field is not stated, return an empty \
string or an empty list for it."""

_USER = """Extract the requirements from this job posting.

Return JSON with exactly these keys:
  "title": the role title as posted
  "company": the hiring company
  "seniority": one of intern, entry, mid, senior, staff, lead, or "" if not stated
  "hard_skills": concrete technologies, tools, languages and named methods the posting asks for
  "qualifications": the required and preferred qualifications, one short phrase each
  "responsibilities": what the person will actually do, one short phrase each
  "keywords": the terms a recruiter would search this posting by (max 25)

Keep every item short. Do not add anything the posting does not say.

--- POSTING ---
{posting}
--- END POSTING ---"""


def _merge_terms(primary: list[str], extra: list[str]) -> list[str]:
    """Deterministic hits keep their order and their place; model hits are appended."""
    out, seen = list(primary), {canonical(t).casefold() for t in primary}
    for term in extra:
        name = canonical(str(term).strip())
        if name and name.casefold() not in seen and len(name) < 60:
            seen.add(name.casefold())
            out.append(name)
    return out


def _merge_phrases(primary: list[str], extra: list[str], limit: int = 40) -> list[str]:
    out, seen = list(primary), {normalize(p) for p in primary}
    for phrase in extra:
        text = str(phrase).strip(" .;")
        key = normalize(text)
        if text and key not in seen and len(text) < 300:
            seen.add(key)
            out.append(text)
    return out[:limit]


def enrich(jd: JobDescription, llm_call: LLMCall, *, max_chars: int = 12000) -> JobDescription:
    """One model pass, merged on top of the deterministic result.

    Failures are swallowed on purpose: a posting parsed by lexicon alone still generates a
    résumé, and dying here would make an unreachable endpoint fatal to the whole tool.
    """
    try:
        data = llm_call(_SYSTEM, _USER.format(posting=truncate(jd.raw, max_chars)))
    except LLMError:
        return jd

    def as_list(key: str) -> list[str]:
        value = data.get(key)
        return [str(v) for v in value if str(v).strip()] if isinstance(value, list) else []

    jd.title = jd.title or str(data.get("title") or "").strip()
    jd.company = jd.company or str(data.get("company") or "").strip()
    jd.seniority = jd.seniority or str(data.get("seniority") or "").strip().casefold()
    jd.hard_skills = _merge_terms(jd.hard_skills, as_list("hard_skills"))
    jd.qualifications = _merge_phrases(jd.qualifications, as_list("qualifications"))
    jd.responsibilities = _merge_phrases(jd.responsibilities, as_list("responsibilities"))
    jd.keywords = _merge_terms(_merge_terms(jd.keywords, jd.hard_skills), as_list("keywords"))
    jd.min_years = jd.min_years if jd.min_years is not None else _min_years(jd.qualifications)
    return jd


def parse(text: str, llm_call: LLMCall | None = None) -> JobDescription:
    jd = parse_deterministic(text)
    return enrich(jd, llm_call) if llm_call else jd
