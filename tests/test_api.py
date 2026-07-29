"""The HTTP layer, driven with TestClient and the same scripted model the pipeline tests
use. There is no logic here the CLI does not have, so these tests are about wiring: what
the endpoints return, what they refuse, and that a run really does happen in a thread."""

import pytest
from conftest import needs_chromium
from fastapi.testclient import TestClient
from test_pipeline import FABRICATED, HONEST, HONEST_CEILING, LETTER, POSTING

from resume_fill.config import Settings


@pytest.fixture
def client(monkeypatch, tmp_path, example_profile):
    """A wired-up server: profile on disk, credentials present, model scripted."""
    from resume_fill import main
    from resume_fill.jobs import JobRunner
    from resume_fill.profile import dump_profile

    profile_path = tmp_path / "profile.yaml"
    dump_profile(example_profile, profile_path)

    cfg = Settings(
        LLM_API_KEY="test", LLM_BASE_URL="https://example.invalid", LLM_MODEL="test-model",
        PROFILE_PATH=profile_path, OUT_DIR=tmp_path / "out", EVIDENCE_PATH=tmp_path / "none.json",
        SCORE_THRESHOLD=70, MAX_ITER=2, HOST="127.0.0.1", AUTH_TOKEN="",
    )
    monkeypatch.setattr(main, "settings", cfg)
    monkeypatch.setattr("resume_fill.config.settings", cfg)
    # A fresh runner per test, or the module-level lock leaks between them.
    monkeypatch.setattr(main, "runner", JobRunner())

    responses = {"resume": HONEST, "cover": LETTER}

    def fake(system, user, **kwargs):
        if "Extract the requirements" in user:
            return {}
        return responses["cover"] if "Write a cover letter" in user else responses["resume"]

    monkeypatch.setattr("resume_fill.llm.complete_json", fake)

    test_client = TestClient(main.app)
    test_client.cfg = cfg
    test_client.responses = responses
    test_client.runner = main.runner
    return test_client


# The same posting the pipeline tests use, so the expected ceiling has one definition.
JD = POSTING.raw


# ---------------------------------------------------------------- doctor ----


def test_doctor_reports_structured_checks(client):
    body = client.get("/api/doctor").json()
    assert body["ok"] is True
    names = {c["name"] for c in body["checks"]}
    assert names == {"llm", "profile", "evidence", "chromium", "pdfminer"}


def test_a_missing_evidence_corpus_is_a_warning_not_a_blocker(client):
    """The tool is designed to work without a blog."""
    check = next(c for c in client.get("/api/doctor").json()["checks"] if c["name"] == "evidence")
    assert check["ok"] is False and check["blocking"] is False


def test_doctor_names_the_command_that_fixes_each_problem(client, monkeypatch):
    from resume_fill import main

    monkeypatch.setattr(main, "settings", main.settings.model_copy(update={"LLM_API_KEY": ""}))
    body = client.get("/api/doctor").json()
    llm_check = next(c for c in body["checks"] if c["name"] == "llm")
    assert body["ok"] is False
    assert ".env" in llm_check["fix"]


# ------------------------------------------------------------------ runs ----


def test_runs_is_empty_before_anything_has_been_generated(client):
    assert client.get("/api/runs").json() == {"runs": []}


@needs_chromium
def test_a_full_run_through_the_api(client):
    started = client.post("/api/runs", json={"jd": JD, "mode": "resume"})
    assert started.status_code == 202
    assert client.runner.wait(120)

    current = client.get("/api/runs/current").json()
    assert current["done"] is True and current["ok"] is True and current["error"] is None
    stages = [e["stage"] for e in current["events"]]
    assert stages[0] == "parsing_jd"
    assert "tailoring" in stages and "scored" in stages and stages[-1] == "done"

    runs = client.get("/api/runs").json()["runs"]
    assert len(runs) == 1
    assert runs[0]["company"] == "Northwind"
    assert runs[0]["total"] == HONEST_CEILING
    assert runs[0]["legacy"] is False

    record = client.get(f"/api/runs/{runs[0]['run_id']}").json()
    assert record["score"]["total"] == HONEST_CEILING
    assert [g["keyword"] for g in record["score"]["gaps_absent"]] == ["Kubernetes"]
    # The audit trail the UI renders, with source text embedded.
    claims = record["documents"][0]["claims"]
    assert claims and "asyncio worker pool" in claims[0]["sources"][0]["text"]


@needs_chromium
def test_the_pdf_is_served_inline_so_a_browser_renders_it(client):
    client.post("/api/runs", json={"jd": JD, "mode": "resume"})
    assert client.runner.wait(120)
    run_id = client.get("/api/runs").json()["runs"][0]["run_id"]

    response = client.get(f"/api/runs/{run_id}/files/resume.pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("inline")
    assert response.content[:4] == b"%PDF"


@needs_chromium
def test_starting_a_second_run_while_busy_is_a_409(client):
    """One at a time. The lock is the whole concurrency model."""
    import threading

    from resume_fill import main

    gate = threading.Event()
    original = main._work

    def slow(request, cfg):
        job = original(request, cfg)

        def wrapped(state):
            gate.wait(10)
            job(state)

        return wrapped

    main._work = slow
    try:
        assert client.post("/api/runs", json={"jd": JD}).status_code == 202
        assert client.post("/api/runs", json={"jd": JD}).status_code == 409
    finally:
        gate.set()
        main._work = original
        client.runner.wait(120)


@needs_chromium
def test_a_run_that_cannot_be_grounded_reports_not_ok(client):
    client.responses["resume"] = FABRICATED
    client.post("/api/runs", json={"jd": JD, "mode": "resume"})
    assert client.runner.wait(120)

    current = client.get("/api/runs/current").json()
    assert current["done"] is True and current["ok"] is False
    assert "rejected" in [e["stage"] for e in current["events"]]


def test_current_is_idle_before_anything_runs(client):
    assert client.get("/api/runs/current").json() == {"idle": True}


def test_cancelling_nothing_is_a_409(client):
    assert client.post("/api/runs/current/cancel").status_code == 409


def test_a_run_is_refused_when_the_setup_is_incomplete(client, monkeypatch):
    """Fail before spending an LLM call on a run that cannot finish. The UI blocks the form
    on the same checks; this is the server refusing to be talked into it anyway."""
    from resume_fill import main

    monkeypatch.setattr(main, "settings", main.settings.model_copy(update={"LLM_API_KEY": ""}))
    response = client.post("/api/runs", json={"jd": JD})
    assert response.status_code == 412
    assert response.json()["detail"]["detail"] == "setup incomplete"


def test_an_empty_job_description_is_rejected(client):
    assert client.post("/api/runs", json={"jd": ""}).status_code == 422


def test_an_unknown_mode_is_rejected(client):
    assert client.post("/api/runs", json={"jd": JD, "mode": "poem"}).status_code == 422


# -------------------------------------------------------------- security ----


def test_current_is_not_swallowed_as_a_run_id(client):
    """FastAPI matches routes in declaration order, so /api/runs/current has to be declared
    before /api/runs/{run_id} or it resolves to a run called "current" and 404s."""
    assert client.get("/api/runs/current").status_code == 200
    assert client.post("/api/runs/current/cancel").status_code == 409  # reached the handler


def test_a_run_id_cannot_escape_the_output_directory(client):
    """The id comes from a URL. Without the resolve-and-contain check, `../../.ssh` is a
    perfectly valid run id. Tested against the resolver directly, because an HTTP client
    normalises `..` out of the path before the server ever sees it."""
    import pytest as _pytest
    from fastapi import HTTPException

    from resume_fill.main import _run_dir

    (client.cfg.OUT_DIR / "real-run").mkdir(parents=True)
    assert _run_dir("real-run").name == "real-run"

    for evil in ("..", "../..", "../../etc", "/etc"):
        with _pytest.raises(HTTPException) as exc:
            _run_dir(evil)
        assert exc.value.status_code == 404

    assert client.get("/api/runs/nope/files/resume.pdf").status_code == 404


@needs_chromium
def test_only_files_inside_the_run_are_servable(client):
    client.post("/api/runs", json={"jd": JD, "mode": "resume"})
    assert client.runner.wait(120)
    run_id = client.get("/api/runs").json()["runs"][0]["run_id"]
    assert client.get(f"/api/runs/{run_id}/files/..%2f..%2fprofile.yaml").status_code == 404


def test_a_non_loopback_bind_without_a_token_is_refused():
    """This server reads profile.yaml and spends the user's API key. Binding it to the
    network without a token is an accident waiting for café wifi."""
    from resume_fill.main import check_bind_security, is_local_bind

    assert is_local_bind("127.0.0.1") and is_local_bind("localhost")
    assert not is_local_bind("0.0.0.0")

    check_bind_security("127.0.0.1", "")  # loopback needs nothing
    check_bind_security("0.0.0.0", "a-token")
    with pytest.raises(RuntimeError, match="refusing to bind"):
        check_bind_security("0.0.0.0", "")


def test_mutating_calls_need_the_token_once_the_bind_is_public(client, monkeypatch):
    from resume_fill import main

    monkeypatch.setattr(
        main, "settings", main.settings.model_copy(update={"HOST": "0.0.0.0", "AUTH_TOKEN": "secret"})
    )
    assert client.get("/api/doctor").status_code == 200  # reads stay open by design
    assert client.post("/api/runs", json={"jd": JD}).status_code == 401
    assert client.post(
        "/api/runs", json={"jd": JD}, headers={"Authorization": "Bearer wrong"}
    ).status_code == 401


def test_cross_origin_mutations_are_rejected_on_a_public_bind(client, monkeypatch):
    from resume_fill import main

    monkeypatch.setattr(
        main, "settings", main.settings.model_copy(update={"HOST": "0.0.0.0", "AUTH_TOKEN": "secret"})
    )
    response = client.post(
        "/api/runs", json={"jd": JD},
        headers={"Authorization": "Bearer secret", "Origin": "https://evil.example"},
    )
    assert response.status_code == 403


# ----------------------------------------------------------------- webui ----


def test_the_index_says_how_to_build_the_ui_when_it_is_missing(client, monkeypatch):
    """The built assets are gitignored on purpose, so a fresh clone hits this."""
    from pathlib import Path

    from resume_fill import main

    monkeypatch.setattr(main, "WEBUI_DIR", Path("/definitely/not/built"))
    response = client.get("/")
    assert response.status_code == 503
    assert "npm run build" in response.json()["detail"]


def test_the_built_index_is_served_when_it_exists(client, monkeypatch, tmp_path):
    from resume_fill import main

    built = tmp_path / "webui"
    built.mkdir()
    (built / "index.html").write_text("<!doctype html><title>resume-fill</title>", encoding="utf-8")

    monkeypatch.setattr(main, "WEBUI_DIR", built)
    response = client.get("/")
    assert response.status_code == 200
    assert "resume-fill" in response.text
