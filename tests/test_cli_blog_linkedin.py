import json

from test_ingest_blog import RSS
from test_linkedin_draft import DRAFT

from resume_fill.cli import main
from resume_fill.config import Settings


def test_blog_sync_writes_the_corpus(monkeypatch, tmp_path, capsys):
    evidence_path = tmp_path / "data" / "evidence.json"
    monkeypatch.setattr("resume_fill.config.settings", Settings(EVIDENCE_PATH=evidence_path))
    monkeypatch.setattr(
        "resume_fill.ingest.blog.http_fetcher",
        lambda ua, timeout=30.0: lambda url: {
            "https://blog.example.com": '<link rel="alternate" type="application/rss+xml" href="/rss">',
            "https://blog.example.com/rss": RSS,
        }.get(url),
    )

    assert main(["blog", "sync", "--url", "https://blog.example.com"]) == 0
    corpus = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert corpus["blog_url"] == "https://blog.example.com"
    assert corpus["items"] and corpus["items"][0]["id"].startswith("blog:")
    assert "evidence items from 1 post(s)" in capsys.readouterr().out


def test_blog_sync_without_a_url_says_where_to_put_one(monkeypatch, capsys):
    monkeypatch.setattr("resume_fill.config.settings", Settings(BLOG_URL=""))
    assert main(["blog", "sync"]) == 1
    assert "BLOG_URL" in capsys.readouterr().out


def test_blog_sync_that_finds_nothing_says_the_tool_still_works(monkeypatch, tmp_path, capsys):
    """An empty corpus is a normal state: it only ever adds specifics to bullets the
    profile already supports."""
    monkeypatch.setattr("resume_fill.config.settings",
                        Settings(EVIDENCE_PATH=tmp_path / "evidence.json"))
    monkeypatch.setattr("resume_fill.ingest.blog.http_fetcher",
                        lambda ua, timeout=30.0: lambda url: None)

    assert main(["blog", "sync", "--url", "https://blog.example.com"]) == 1
    printed = capsys.readouterr().out
    assert "nothing found" in printed
    assert "works without a blog" in printed
    assert not (tmp_path / "evidence.json").exists()


def test_linkedin_draft_prints_the_copy_and_says_you_paste_it(
    monkeypatch, tmp_path, example_profile, capsys
):
    from resume_fill.profile import dump_profile

    profile_path = tmp_path / "profile.yaml"
    dump_profile(example_profile, profile_path)
    monkeypatch.setattr(
        "resume_fill.config.settings",
        Settings(LLM_API_KEY="k", LLM_BASE_URL="u", LLM_MODEL="m", PROFILE_PATH=profile_path,
                 EVIDENCE_PATH=tmp_path / "none.json", OUT_DIR=tmp_path / "out",
                 LINKEDIN_EXPORT_DIR=tmp_path / "no-export"),
    )
    monkeypatch.setattr("resume_fill.llm.complete_json", lambda s, u, **kw: DRAFT)

    out_path = tmp_path / "draft.md"
    assert main(["linkedin", "draft", "--out", str(out_path)]) == 0

    body = out_path.read_text(encoding="utf-8")
    assert "## Headline" in body and "```diff" in body
    printed = capsys.readouterr().out
    assert "no public write API" in printed
    assert "This prints copy; you paste it." in printed
    # Without an export, the diff is against the record and understates the change.
    assert "understate" in printed


def test_linkedin_draft_that_cannot_be_grounded_fails(monkeypatch, tmp_path, example_profile, capsys):
    from resume_fill.profile import dump_profile

    profile_path = tmp_path / "profile.yaml"
    dump_profile(example_profile, profile_path)
    monkeypatch.setattr(
        "resume_fill.config.settings",
        Settings(LLM_API_KEY="k", LLM_BASE_URL="u", LLM_MODEL="m", PROFILE_PATH=profile_path,
                 EVIDENCE_PATH=tmp_path / "none.json", OUT_DIR=tmp_path / "out", MAX_ITER=1),
    )
    bad = {**DRAFT, "headline": {"text": "Kubernetes specialist", "source_ids": ["skills"]}}
    monkeypatch.setattr("resume_fill.llm.complete_json", lambda s, u, **kw: bad)

    assert main(["linkedin", "draft", "--out", str(tmp_path / "draft.md")]) == 1
    assert "do not paste it as-is" in capsys.readouterr().out


def test_doctor_still_reports_on_the_new_sources(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("resume_fill.config.settings",
                        Settings(EVIDENCE_PATH=tmp_path / "nope.json"))
    main(["doctor"])
    assert "resume-fill blog sync" in capsys.readouterr().out
