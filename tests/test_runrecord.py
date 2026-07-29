import json

from resume_fill import runrecord
from resume_fill.document import Bullet, CoverLetter, ResumeDoc, SelectedEntry
from resume_fill.jd import parse_deterministic
from resume_fill.score import score

JD = parse_deterministic("Backend Engineer\n\nAbout Northwind\n\nRequirements\n- Python\n- Kubernetes\n")

DOC = ResumeDoc(
    experience=[
        SelectedEntry(
            source_id="exp-northwind-backend",
            bullets=[
                Bullet(
                    text="Rewrote the nightly ingestion job, cutting the run from 51 minutes to 9.",
                    source_ids=["exp-northwind-backend.h1"],
                )
            ],
        )
    ],
    skills={"Languages": ["Python"]},
)


def test_claims_embed_the_source_text_not_just_the_id(example_profile):
    index = example_profile.sources()
    claims = runrecord.resume_claims(DOC, index)

    assert len(claims) == 1
    assert claims[0].where == "experience[exp-northwind-backend].bullet1"
    source = claims[0].sources[0]
    assert source.id == "exp-northwind-backend.h1"
    assert "asyncio worker pool" in source.text  # the snapshot, not a pointer


def test_the_audit_survives_an_edit_to_the_record(example_profile, tmp_path):
    """The whole reason source text is embedded.

    A citation is a receipt for a claim on a document you may already have sent. Closing a
    gap means editing profile.yaml — which the tool actively encourages — and if the audit
    re-read the record it would silently start showing a source that no longer says what it
    said. It would still render, and it would be wrong, and nothing would say so.
    """
    index = example_profile.sources()
    record = runrecord.RunRecord(
        run_id="r", created_at=runrecord.now(), mode="resume",
        documents=[runrecord.DocumentRecord(kind="resume", claims=runrecord.resume_claims(DOC, index))],
    )
    runrecord.save(record, tmp_path)

    # Now rewrite history: the highlight this résumé cited gets reworded.
    edited = example_profile.model_copy(deep=True)
    edited.experience[0].highlights[0].text = "Something completely different."
    assert "asyncio" not in edited.sources()["exp-northwind-backend.h1"].text

    reloaded = runrecord.load(tmp_path)
    assert "asyncio worker pool" in reloaded.documents[0].claims[0].sources[0].text


def test_cover_letter_claims_use_the_same_shape(example_profile):
    letter = CoverLetter(
        addressee="Hiring Manager",
        paragraphs=[{"text": "I rewrote the ingestion job.", "source_ids": ["exp-northwind-backend.h1"]}],
    )
    claims = runrecord.cover_claims(letter, example_profile.sources())
    assert claims[0].where == "paragraph1"
    assert claims[0].sources[0].label


def test_a_citation_to_a_vanished_id_is_dropped_not_fatal(example_profile):
    doc = ResumeDoc(
        experience=[
            SelectedEntry(source_id="exp-northwind-backend",
                          bullets=[Bullet(text="x", source_ids=["gone"])])
        ]
    )
    claims = runrecord.resume_claims(doc, example_profile.sources())
    assert claims[0].sources == []


def test_score_record_splits_the_two_kinds_of_gap(example_profile):
    """They mean different things, so they are split at write time. A consumer that has to
    remember to filter will eventually forget."""
    result = score(DOC, example_profile, JD, example_profile.sources())
    record = runrecord.score_record(result, threshold=80.0)

    assert record.total == result.total
    assert record.met is False
    assert [g.keyword for g in record.gaps_absent] == ["Kubernetes"]
    assert all(g.in_record for g in record.gaps_unsurfaced)
    assert len(record.components) == 5


def test_score_record_is_none_when_there_was_no_score():
    assert runrecord.score_record(None, 80.0) is None


# ------------------------------------------------------------- io / scan ----


def _write(tmp_path, name, **kwargs):
    d = tmp_path / name
    d.mkdir(parents=True)
    runrecord.save(
        runrecord.RunRecord(run_id=name, created_at=kwargs.pop("created_at", "2026-07-01T00:00:00+00:00"),
                            mode="both", **kwargs),
        d,
    )
    return d


def test_save_and_load_round_trip(tmp_path):
    _write(tmp_path, "acme-2026-07-01", ok=True)
    loaded = runrecord.load(tmp_path / "acme-2026-07-01")
    assert loaded.run_id == "acme-2026-07-01"
    assert loaded.schema_version == runrecord.SCHEMA_VERSION


def test_scan_lists_newest_first(tmp_path):
    _write(tmp_path, "old", created_at="2026-07-01T00:00:00+00:00")
    _write(tmp_path, "new", created_at="2026-07-20T00:00:00+00:00")
    assert [s.run_id for s in runrecord.scan(tmp_path)] == ["new", "old"]


def test_a_run_from_before_run_json_existed_is_still_listed(tmp_path):
    """Crashing on it, or hiding it, would both be worse: the PDFs are still there and
    still worth downloading."""
    legacy = tmp_path / "legacy-run"
    legacy.mkdir()
    (legacy / "resume.pdf").write_bytes(b"%PDF-1.4")

    summary = runrecord.summarize(legacy)
    assert summary.legacy is True
    assert summary.pdfs == ["resume.pdf"]
    assert summary.total is None
    assert summary.created_at  # falls back to the directory mtime


def test_a_malformed_record_does_not_take_down_the_listing(tmp_path):
    good = _write(tmp_path, "good")
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / runrecord.FILENAME).write_text("{not json", encoding="utf-8")

    assert runrecord.load(bad) is None
    ids = {s.run_id for s in runrecord.scan(tmp_path)}
    assert ids == {"good", "bad"}
    assert next(s for s in runrecord.scan(tmp_path) if s.run_id == "bad").legacy is True
    assert good.exists()


def test_scan_of_a_missing_directory_is_empty(tmp_path):
    assert runrecord.scan(tmp_path / "never-generated") == []


def test_read_json_passes_the_record_through_untouched(tmp_path):
    d = _write(tmp_path, "acme", ok=True)
    raw = runrecord.read_json(d)
    assert raw == json.loads((d / runrecord.FILENAME).read_text(encoding="utf-8"))
    assert runrecord.read_json(tmp_path / "nope") is None
