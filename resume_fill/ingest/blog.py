"""Blog -> `data/evidence.json`.

A blog contains narrative, not skeleton (PLAN.md §2): no employers, titles, dates, degree
or contact details. So this can never be the résumé's source of truth. What it is good for
is the specific — *how* a thing was built — which profile.yaml usually records only as
"built it". A bullet can cite a paragraph from here and say something concrete.

PLAN.md open question 1 was "which blog?", blocking all of M6. Resolved by not needing the
answer: BLOG_URL is config, and the ingestion mechanics (RSS vs Atom vs sitemap vs plain
HTML) are autodetected in that order rather than chosen up front. Point it at anything.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

from ..evidence import Corpus, EvidenceItem
from ..jd import strip_html
from ..profile import slug

# A fetcher returns the body of a URL, or None if it could not be read. Injectable so the
# tests exercise real feed/sitemap/HTML parsing without a network.
Fetcher = Callable[[str], "str | None"]

# Feeds and pages are not adversarial here — it is the user's own blog — but a runaway
# response should not be able to fill memory.
MAX_BYTES = 5_000_000
CHUNK_CHARS = 700
# Filtering happens per paragraph, not per chunk. A chunk minimum would throw away "the old
# job took 51 minutes on a good night" — short, and exactly the kind of sentence a bullet
# wants to cite. A word minimum drops navigation and captions without touching prose.
MIN_PARAGRAPH_WORDS = 8
# A feed carrying less than this is a teaser, and the page is worth fetching for the rest.
TEASER_CHARS = 240

_FEED_LINK = re.compile(
    r"""<link[^>]+rel=["']alternate["'][^>]*>""", re.I,
)
_HREF = re.compile(r"""href=["']([^"']+)["']""", re.I)
_TYPE = re.compile(r"""type=["']([^"']+)["']""", re.I)
_FEED_TYPES = ("application/rss+xml", "application/atom+xml", "application/feed+json")

_COMMON_FEEDS = ("feed", "feed.xml", "rss.xml", "atom.xml", "index.xml", "feed/", "rss")
_ARTICLE = re.compile(r"(?is)<(article|main)\b[^>]*>(.*?)</\1>")
_TITLE = re.compile(r"(?is)<title[^>]*>(.*?)</title>")
_H1 = re.compile(r"(?is)<h1[^>]*>(.*?)</h1>")
_PUBLISHED = re.compile(
    r"""(?is)<meta[^>]+(?:property|name)=["']article:published_time["'][^>]+content=["']([^"']+)["']"""
)
_TIME_TAG = re.compile(r"""(?is)<time[^>]+datetime=["']([^"']+)["']""")
_LINK_HREF = re.compile(r"""(?is)<a[^>]+href=["']([^"']+)["']""")
_DATEISH = re.compile(r"(\d{4}-\d{2}-\d{2})|(\d{4}/\d{2}/\d{2})")


@dataclass
class Post:
    url: str
    title: str = ""
    date: str = ""
    text: str = ""


def http_fetcher(user_agent: str, timeout: float = 30.0) -> Fetcher:
    import httpx

    client = httpx.Client(
        follow_redirects=True, timeout=timeout, headers={"User-Agent": user_agent}
    )

    def fetch(url: str) -> str | None:
        try:
            response = client.get(url)
            response.raise_for_status()
        except Exception:
            # One unreachable post must not abort a sync of fifty.
            return None
        return response.text[:MAX_BYTES]

    return fetch


# ---------------------------------------------------------------- feeds ----


def feed_urls_in(html: str, base: str) -> list[str]:
    """<link rel="alternate" type="application/rss+xml"> — the declared feed, when there
    is one. Preferred over guessing because a blog that declares its feed is telling you
    which one is canonical."""
    found = []
    for tag in _FEED_LINK.findall(html or ""):
        type_match, href_match = _TYPE.search(tag), _HREF.search(tag)
        if href_match and type_match and type_match.group(1).lower() in _FEED_TYPES:
            found.append(urljoin(base, href_match.group(1)))
    return found


def _text_of(element, *names: str) -> str:
    """Read a child element by local name, ignoring the namespace.

    RSS 2.0, RSS 1.0 and Atom all spell the same fields differently and half the feeds in
    the wild get their own namespace declarations wrong, so matching on the local name is
    the only thing that works across all of them.
    """
    for child in element.iter():
        tag = child.tag.rsplit("}", 1)[-1].lower()
        if tag in names:
            if child.text and child.text.strip():
                return child.text.strip()
            # Atom puts the link in an attribute rather than in the text.
            if tag == "link" and child.get("href"):
                return child.get("href", "").strip()
    return ""


def parse_feed(xml: str, base: str) -> list[Post]:
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return []
    posts = []
    for entry in root.iter():
        if entry.tag.rsplit("}", 1)[-1].lower() not in ("item", "entry"):
            continue
        link = _text_of(entry, "link", "id", "guid")
        if not link.startswith("http"):
            link = urljoin(base, link)
        body = _text_of(entry, "encoded", "content", "description", "summary")
        posts.append(
            Post(
                url=link,
                title=_text_of(entry, "title"),
                date=normalize_date(_text_of(entry, "published", "pubdate", "updated", "date")),
                text=strip_html(body),
            )
        )
    return posts


def normalize_date(value: str) -> str:
    """Whatever the feed said, reduced to YYYY-MM-DD when it can be. Dates on evidence are
    context for a human reading report.md, not something anything computes with."""
    text = (value or "").strip()
    if match := re.search(r"(\d{4})-(\d{2})-(\d{2})", text):
        return match.group(0)
    if match := re.search(r"(\d{1,2})\s+([A-Za-z]{3})[a-z]*\s+(\d{4})", text):  # RFC 822
        months = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
        month = months.index(match.group(2).lower()[:3]) + 1
        return f"{match.group(3)}-{month:02d}-{int(match.group(1)):02d}"
    return text[:10]


# ------------------------------------------------------------- sitemaps ----


def parse_sitemap(xml: str) -> list[str]:
    """Handles both a urlset and a sitemap index, one level deep is enough for a blog."""
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return []
    return [
        node.text.strip()
        for node in root.iter()
        if node.tag.rsplit("}", 1)[-1].lower() == "loc" and node.text and node.text.strip()
    ]


def looks_like_a_post(url: str, root: str) -> bool:
    """Same origin, deeper than the landing page, and not an obvious index or asset."""
    parsed, root_parsed = urlparse(url), urlparse(root)
    if parsed.netloc != root_parsed.netloc:
        return False
    path = parsed.path.rstrip("/")
    if not path or path.count("/") < 1:
        return False
    if re.search(r"\.(png|jpe?g|gif|svg|css|js|xml|json|pdf|ico|webp)$", path, re.I):
        return False
    return not re.search(r"/(tags?|categor(y|ies)|page|author|about|archive)s?(/|$)", path, re.I)


# ---------------------------------------------------------------- pages ----


def extract_post(html: str, url: str) -> Post:
    """<article> or <main> if the page marks one, otherwise the whole body.

    No readability heuristic beyond that: guessing which div is the content is how a
    scraper starts quoting a sidebar into someone's résumé.
    """
    body = match.group(2) if (match := _ARTICLE.search(html or "")) else (html or "")
    title = ""
    if match := _H1.search(body) or _H1.search(html or "") or _TITLE.search(html or ""):
        title = strip_html(match.group(1))
    date = ""
    for pattern in (_PUBLISHED, _TIME_TAG):
        if match := pattern.search(html or ""):
            date = normalize_date(match.group(1))
            break
    if not date and (match := _DATEISH.search(url)):
        date = match.group(0).replace("/", "-")
    return Post(url=url, title=title, date=date, text=strip_html(body))


def chunk_post(post: Post, *, chars: int = CHUNK_CHARS) -> list[EvidenceItem]:
    """Paragraph-aligned chunks, ids stable across syncs.

    Stability matters: an id in this corpus can be cited by a bullet in a résumé you
    already sent, and report.md is the record of what backed it.
    """
    title_key = " ".join((post.title or "").split()).casefold()
    paragraphs = [
        text
        for raw in re.split(r"\n\s*\n", post.text or "")
        if (text := raw.strip())
        and len(text.split()) >= MIN_PARAGRAPH_WORDS
        # The <h1> repeats the title verbatim and the title is already on every item.
        and " ".join(text.split()).casefold() != title_key
    ]

    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if current and len(current) + len(paragraph) > chars:
            chunks.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}" if current else paragraph
    if current:
        chunks.append(current)

    name = slug(post.title or urlparse(post.url).path.strip("/").replace("/", "-") or "post", 40)
    return [
        EvidenceItem(id=f"blog:{name}#{i}", title=post.title, url=post.url, date=post.date, text=text)
        for i, text in enumerate(chunks, start=1)
    ]


# ----------------------------------------------------------------- sync ----


def discover(blog_url: str, fetch: Fetcher) -> tuple[list[Post], str]:
    """Feed first, then a guessed feed, then the sitemap, then links off the landing page.

    Returns the posts and a one-line note saying which route worked, because when a sync
    produces three items instead of thirty the first question is always which one it used.
    """
    landing = fetch(blog_url) or ""

    for feed_url in feed_urls_in(landing, blog_url):
        if (xml := fetch(feed_url)) and (posts := parse_feed(xml, blog_url)):
            return posts, f"declared feed ({feed_url})"

    for candidate in _COMMON_FEEDS:
        url = urljoin(blog_url.rstrip("/") + "/", candidate)
        if (xml := fetch(url)) and (posts := parse_feed(xml, blog_url)):
            return posts, f"feed at {url}"

    for candidate in ("sitemap.xml", "sitemap_index.xml"):
        url = urljoin(blog_url.rstrip("/") + "/", candidate)
        if xml := fetch(url):
            urls = [u for u in parse_sitemap(xml) if looks_like_a_post(u, blog_url)]
            if urls:
                return [Post(url=u) for u in urls], f"sitemap at {url}"

    links = []
    for href in _LINK_HREF.findall(landing):
        url = urljoin(blog_url, href.split("#")[0])
        if looks_like_a_post(url, blog_url) and url not in links:
            links.append(url)
    return [Post(url=u) for u in links], "links on the landing page"


def sync(blog_url: str, fetch: Fetcher, *, max_posts: int = 100) -> tuple[Corpus, str]:
    if not blog_url:
        raise ValueError("BLOG_URL is not set - put your blog's address in .env")

    posts, route = discover(blog_url, fetch)
    posts = posts[:max_posts]
    items: list[EvidenceItem] = []
    fetched = 0
    for post in posts:
        # Feeds that carry only a summary are worth a page fetch; ones with full content
        # are not, and re-fetching fifty pages to learn nothing is the slow way to sync.
        if len(post.text) < TEASER_CHARS:
            if html := fetch(post.url):
                page = extract_post(html, post.url)
                post = Post(
                    url=post.url,
                    title=post.title or page.title,
                    date=post.date or page.date,
                    text=page.text if len(page.text) > len(post.text) else post.text,
                )
                fetched += 1
        items.extend(chunk_post(post))

    note = f"{len(items)} evidence items from {len(posts)} post(s) via {route}"
    if fetched:
        note += f"; {fetched} page(s) fetched for full text"
    return Corpus(blog_url=blog_url, items=items), note
