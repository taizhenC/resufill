"""Text primitives shared by the grounding gate, the scorer and the PDF verifier.

All three ask variants of one question — "does this string say that thing?" — and they
have to agree, or a bullet can pass grounding and then fail scoring for the same words.
So the matching rules live here once.
"""

import re
import unicodedata

# Typographic characters that survive a copy-paste from a job posting and would otherwise
# make an exact match fail for no real reason.
_PUNCT_MAP = {
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "−": "-", " ": " ",
    "•": " ", "‣": " ", "▪": " ", "·": " ",
}
_WS = re.compile(r"\s+")
_WORD = re.compile(r"[A-Za-z][A-Za-z'\-]*")

# A standalone quantity: 40%, $1.2M, 3x, 12,000, 2.5. Deliberately *not* matching numerals
# glued to letters (S3, EC2, Python3, H100) — those are product names, and they are checked
# as technical terms instead, where a real lexicon can vouch for them.
_NUMBER = re.compile(
    r"(?<![A-Za-z0-9.])\$?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*"
    r"(%|percent|x\b|k\b|m\b|b\b|bn\b|mm\b|million|billion|thousand)?",
    re.IGNORECASE,
)


def normalize(text: str) -> str:
    """Casefolded, punctuation-unified, whitespace-collapsed. The form every comparison uses."""
    text = unicodedata.normalize("NFKC", text or "")
    for src, dst in _PUNCT_MAP.items():
        text = text.replace(src, dst)
    return _WS.sub(" ", text).strip().casefold()


def squash(text: str) -> str:
    """Drop everything but letters and digits, so "Node.js" == "nodejs" == "node js"
    and "CI/CD" == "cicd". Used only as a fallback after an exact match fails."""
    return re.sub(r"[^a-z0-9]+", "", normalize(text))


def _bounded(core: str, needle: str) -> str:
    """Wrap a pattern in alphanumeric boundaries, but only on the edges that are themselves
    alphanumeric. Plain \\b does the wrong thing on exactly the terms that matter most:
    "C++" ends on punctuation, and ".NET" starts on it."""
    left = r"(?<![a-z0-9])" if needle[:1].isalnum() else ""
    right = r"(?![a-z0-9])" if needle[-1:].isalnum() else ""
    return f"{left}{core}{right}"


def contains_term(haystack: str, term: str) -> bool:
    """Does `haystack` contain `term` as a term, not as a substring?

    Two passes. The literal spelling first, then — only for terms written with internal
    punctuation — a variant that lets the separators differ, so "Node.js" finds "nodejs"
    and "CI/CD" finds "CICD".

    The variant is built from the term's own alphanumeric runs rather than by squashing
    both sides, because squashing is far too eager: ".NET" squashes to "net", which appears
    inside "Kubernetes", which would silently license a claim about a framework nobody
    named.
    """
    hay, needle = normalize(haystack), normalize(term)
    if not needle:
        return False
    if re.search(_bounded(re.escape(needle), needle), hay):
        return True
    runs = re.findall(r"[a-z0-9]+", needle)
    if len(runs) < 2:
        return False
    core = r"[^a-z0-9]{0,2}".join(re.escape(run) for run in runs)
    return bool(re.search(_bounded(core, runs[0] + runs[-1]), hay))


def words(text: str) -> list[str]:
    return _WORD.findall(normalize(text))


def numbers(text: str) -> list[str]:
    """Every standalone quantity, as it was written (minus thousands separators)."""
    out = []
    for value, unit in _NUMBER.findall(text or ""):
        value = value.replace(",", "")
        out.append(f"{value}{(unit or '').strip().lower()}")
    return out


def numeral_of(claim: str) -> str:
    """"40%" -> "40", "12,000" -> "12000". The bare figure, which is what has to appear in
    the source. Commas go first, or "12,000" would reduce to "12"."""
    match = re.match(r"\d+(?:\.\d+)?", (claim or "").replace(",", ""))
    return match.group(0) if match else claim


def supports_number(haystack: str, claim: str) -> bool:
    """Is this quantity backed by the source text?

    The figure itself must be there. The *unit* is allowed to differ, because "cut latency
    40%" and a source note reading "p95 went from 500ms to 300ms, about 40 percent" are the
    same fact stated twice — and requiring the unit to match would reject the bullet while
    letting a genuinely invented "40%" through whenever the source happened to say "40 users".
    That trade is why report.md prints the citation next to every number.
    """
    numeral = numeral_of(claim)
    hay = normalize(haystack).replace(",", "")
    if re.search(rf"(?<![0-9.]){re.escape(numeral)}(?![0-9])", hay):
        return True
    # 3.0 in the source backs a claim of 3, and vice versa.
    try:
        target = float(numeral)
    except ValueError:
        return False
    return any(abs(float(n) - target) < 1e-9 for n in re.findall(r"\d+(?:\.\d+)?", hay))


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text or "")
    return [p.strip() for p in parts if p.strip()]


def truncate(text: str, limit: int) -> str:
    """Cut on a word boundary where there is one nearby. These strings end up as citation
    labels in report.md, and "...single-threaded cro" reads as a bug."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rstrip()
    space = cut.rfind(" ")
    if space > limit * 0.6:
        cut = cut[:space]
    return cut.rstrip(" ,;:-") + "…"
