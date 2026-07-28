"""Blog ingestion, against fake sites rather than a network.

Every discovery route is exercised, because which one fires is the difference between a
corpus of thirty items and a corpus of three, and a blog only tells you which it supports
by responding.
"""

from resume_fill.ingest.blog import (
    chunk_post,
    discover,
    extract_post,
    feed_urls_in,
    looks_like_a_post,
    normalize_date,
    parse_feed,
    parse_sitemap,
    sync,
)

RSS = """<?xml version="1.0"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel>
  <title>Ada writes</title>
  <item>
    <title>Rewriting a cron script as an asyncio pool</title>
    <link>https://blog.example.com/posts/asyncio-pool</link>
    <pubDate>Mon, 14 Jul 2025 09:00:00 +0000</pubDate>
    <content:encoded><![CDATA[<p>The old job was a single-threaded cron script.</p>
    <p>I moved it to an asyncio worker pool with a bounded semaphore, which is the part that
    actually mattered: without the bound it opened 200 Postgres connections and fell over.</p>]]></content:encoded>
  </item>
</channel>
</rss>"""

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Ada writes</title>
  <entry>
    <title>Packing NOAA tide tables into SQLite</title>
    <link href="https://blog.example.com/posts/tides"/>
    <updated>2025-03-02T10:00:00Z</updated>
    <summary>short</summary>
  </entry>
</feed>"""

SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://blog.example.com/posts/asyncio-pool</loc></url>
  <url><loc>https://blog.example.com/tags/python</loc></url>
  <url><loc>https://blog.example.com/logo.png</loc></url>
</urlset>"""

POST_HTML = """<html><head>
<title>Rewriting a cron script | Ada writes</title>
<meta property="article:published_time" content="2025-07-14T09:00:00Z">
</head><body>
<nav>Home Archive Tags</nav>
<article>
<h1>Rewriting a cron script as an asyncio pool</h1>
<p>The old job was a single-threaded cron script that took 51 minutes on a good night.</p>
<p>I moved it to an asyncio worker pool with a bounded semaphore. The bound is the part that
mattered: without it the pool opened 200 Postgres connections and the database fell over.</p>
</article>
<aside>Subscribe to my newsletter! Buy my course!</aside>
</body></html>"""


def _site(pages: dict[str, str]):
    return lambda url: pages.get(url)


# ------------------------------------------------------------ discovery ----


def test_a_declared_feed_is_preferred_over_guessing():
    """A blog that declares its feed is telling you which one is canonical."""
    landing = (
        '<html><head><link rel="alternate" type="application/rss+xml" href="/atom.xml">'
        "</head><body></body></html>"
    )
    assert feed_urls_in(landing, "https://blog.example.com/") == ["https://blog.example.com/atom.xml"]

    posts, route = discover(
        "https://blog.example.com/",
        _site({"https://blog.example.com/": landing, "https://blog.example.com/atom.xml": RSS}),
    )
    assert [p.title for p in posts] == ["Rewriting a cron script as an asyncio pool"]
    assert "declared feed" in route


def test_a_feed_at_a_conventional_path_is_found_without_a_declaration():
    posts, route = discover(
        "https://blog.example.com",
        _site({"https://blog.example.com": "<html></html>", "https://blog.example.com/feed": RSS}),
    )
    assert len(posts) == 1
    assert "feed at https://blog.example.com/feed" in route


def test_the_sitemap_is_the_third_route():
    posts, route = discover(
        "https://blog.example.com",
        _site({"https://blog.example.com": "<html></html>",
               "https://blog.example.com/sitemap.xml": SITEMAP}),
    )
    assert [p.url for p in posts] == ["https://blog.example.com/posts/asyncio-pool"]
    assert "sitemap" in route


def test_landing_page_links_are_the_last_resort():
    landing = (
        '<html><body><a href="/posts/asyncio-pool">one</a>'
        '<a href="/tags/python">tag</a>'
        '<a href="https://twitter.com/ada">off-site</a>'
        '<a href="/about">about</a></body></html>'
    )
    posts, route = discover("https://blog.example.com", _site({"https://blog.example.com": landing}))
    assert [p.url for p in posts] == ["https://blog.example.com/posts/asyncio-pool"]
    assert "landing page" in route


def test_looks_like_a_post_rejects_indexes_assets_and_other_sites():
    root = "https://blog.example.com/"
    assert looks_like_a_post("https://blog.example.com/posts/one", root)
    assert not looks_like_a_post("https://blog.example.com/", root)
    assert not looks_like_a_post("https://blog.example.com/tags/python", root)
    assert not looks_like_a_post("https://blog.example.com/style.css", root)
    assert not looks_like_a_post("https://other.example.com/posts/one", root)


# --------------------------------------------------------------- parsing ----


def test_rss_and_atom_are_read_by_the_same_parser():
    """RSS 2.0 and Atom spell every field differently, and half the feeds in the wild get
    their namespace declarations wrong, so matching on the local name is what works."""
    rss = parse_feed(RSS, "https://blog.example.com")
    assert rss[0].date == "2025-07-14"
    assert "asyncio worker pool" in rss[0].text

    atom = parse_feed(ATOM, "https://blog.example.com")
    assert atom[0].title == "Packing NOAA tide tables into SQLite"
    assert atom[0].url == "https://blog.example.com/posts/tides"  # Atom puts it in an attribute
    assert atom[0].date == "2025-03-02"


def test_malformed_xml_is_not_fatal():
    assert parse_feed("<rss><item>", "https://x") == []
    assert parse_sitemap("not xml at all") == []


def test_normalize_date_handles_rfc822_and_iso():
    assert normalize_date("Mon, 14 Jul 2025 09:00:00 +0000") == "2025-07-14"
    assert normalize_date("2025-07-14T09:00:00Z") == "2025-07-14"
    assert normalize_date("") == ""


def test_extract_post_keeps_the_article_and_drops_the_furniture():
    """Guessing which div is the content is how a scraper starts quoting a sidebar into
    someone's résumé, so this only trusts <article>/<main>."""
    post = extract_post(POST_HTML, "https://blog.example.com/posts/asyncio-pool")
    assert post.title == "Rewriting a cron script as an asyncio pool"
    assert post.date == "2025-07-14"
    assert "bounded semaphore" in post.text
    assert "newsletter" not in post.text
    assert "Archive Tags" not in post.text


# -------------------------------------------------------------- chunking ----


def test_chunks_are_paragraph_aligned_with_stable_ids():
    """An id here can be cited by a bullet in a résumé you already sent, and report.md is
    the record of what backed it."""
    post = extract_post(POST_HTML, "https://blog.example.com/posts/asyncio-pool")
    items = chunk_post(post, chars=120)
    assert len(items) == 2
    assert [i.id for i in items] == [
        "blog:rewriting-a-cron-script-as-an-asyncio#1",
        "blog:rewriting-a-cron-script-as-an-asyncio#2",
    ]
    assert chunk_post(post, chars=120)[0].id == items[0].id  # stable across runs


def test_a_short_but_specific_sentence_survives_chunking():
    """Filtering by chunk length would drop "the old job took 51 minutes on a good night" —
    short, and exactly the kind of sentence a bullet wants to cite."""
    post = extract_post(POST_HTML, "https://blog.example.com/posts/asyncio-pool")
    assert "51 minutes" in chunk_post(post, chars=120)[0].text


def test_navigation_and_the_repeated_title_are_dropped():
    from resume_fill.ingest.blog import Post

    post = Post(
        url="https://x/y",
        title="How I did the thing",
        text="How I did the thing\n\nHome Archive Tags\n\n"
        "This paragraph is long enough to count as real prose about the work.",
    )
    items = chunk_post(post)
    assert len(items) == 1
    assert items[0].text.startswith("This paragraph")


def test_a_post_with_nothing_but_furniture_yields_nothing():
    from resume_fill.ingest.blog import Post

    assert chunk_post(Post(url="https://x/y", title="t", text="too short")) == []


# ------------------------------------------------------------------ sync ----


def test_sync_fetches_the_page_when_the_feed_only_carries_a_summary():
    """Feeds that carry full content are not re-fetched; ones that carry a teaser are."""
    fetched: list[str] = []

    def fetch(url: str):
        fetched.append(url)
        return {
            "https://blog.example.com": '<link rel="alternate" type="application/atom+xml" href="/atom">',
            "https://blog.example.com/atom": ATOM,
            "https://blog.example.com/posts/tides": POST_HTML,
        }.get(url)

    corpus, note = sync("https://blog.example.com", fetch)
    assert "https://blog.example.com/posts/tides" in fetched
    assert "1 page(s) fetched for full text" in note
    assert corpus.items and "bounded semaphore" in corpus.items[0].text


def test_sync_does_not_refetch_a_full_content_feed():
    def fetch(url: str):
        return {
            "https://blog.example.com": '<link rel="alternate" type="application/rss+xml" href="/rss">',
            "https://blog.example.com/rss": RSS,
        }.get(url)

    corpus, note = sync("https://blog.example.com", fetch)
    assert "fetched for full text" not in note
    assert corpus.items


def test_sync_respects_the_post_cap():
    many = "".join(
        f"<url><loc>https://blog.example.com/posts/p{i}</loc></url>" for i in range(50)
    )
    fetch = _site({
        "https://blog.example.com": "<html></html>",
        "https://blog.example.com/sitemap.xml":
            f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{many}</urlset>',
    })
    _, note = sync("https://blog.example.com", fetch, max_posts=3)
    assert "from 3 post(s)" in note


def test_sync_without_a_blog_url_says_where_to_put_one():
    import pytest

    with pytest.raises(ValueError, match="BLOG_URL"):
        sync("", _site({}))


def test_the_corpus_becomes_citable_sources():
    fetch = _site({
        "https://blog.example.com": '<link rel="alternate" type="application/rss+xml" href="/rss">',
        "https://blog.example.com/rss": RSS,
    })
    corpus, _ = sync("https://blog.example.com", fetch)
    sources = corpus.sources()
    first = next(iter(sources.values()))
    assert first.kind == "evidence"
    assert "asyncio" in first.text
