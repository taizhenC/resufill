"""The local web server: a thin JSON API over the library the CLI already uses.

There is no logic here that the CLI does not have. `pipeline.run()` already took a
progress callback and already wrote everything to `out/`, so this layer parses a request,
hands the work to a thread, and reads files back. If something needs to change in how a
résumé is made, it changes in the pipeline, not here.

Scope is the generate loop only. `init`, `blog sync` and `linkedin draft` stay CLI-only:
they are once-a-year commands, and `init` in particular exists to produce a file you then
correct by hand in an editor.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import doctor, evidence, llm, runrecord
from . import jd as jd_module
from . import score as score_module
from .config import PACKAGE_DIR, settings
from .jobs import Busy, JobRunner, JobState
from .pipeline import MODES, run, run_dir, source_index
from .profile import ProfileError, load_profile
from .progress import PARSING_JD, Progress
from .textutil import contains_term

WEBUI_DIR = PACKAGE_DIR / "webui"
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", ""}

runner = JobRunner()


def is_local_bind(host: str) -> bool:
    return host in LOOPBACK_HOSTS


def check_bind_security(host: str, auth_token: str) -> None:
    """Refuse the footgun.

    This server reads `profile.yaml` — full name, phone, email, employment history — and
    every POST spends the user's own API key. Binding it to the network without a token is
    not a configuration choice, it is an accident waiting for café wifi.
    """
    if not is_local_bind(host) and not auth_token:
        raise RuntimeError(
            f"refusing to bind {host}: set AUTH_TOKEN in .env before exposing resume-fill "
            "beyond this machine — without it, anyone on the network can read your contact "
            "details and employment history and spend YOUR API key. Mutating requests must "
            "then send the header 'Authorization: Bearer <token>'."
        )


app = FastAPI(title="resume-fill", docs_url=None, redoc_url=None)

MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@app.middleware("http")
async def security_gate(request: Request, call_next):
    """Active only for non-local binds: bearer token on every mutating API call, plus a
    same-origin check against cross-site browser requests. Reads stay open by design — the
    token protects actions, and on a loopback bind there is nothing to protect against."""
    if (
        not is_local_bind(settings.HOST)
        and request.method in MUTATING_METHODS
        and request.url.path.startswith("/api/")
    ):
        origin = request.headers.get("origin")
        if origin:
            host = request.headers.get("host", "")
            if urlsplit(origin).netloc.lower() != host.lower():
                return JSONResponse(status_code=403, content={"detail": "cross-origin request rejected"})
        supplied = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if not settings.AUTH_TOKEN or not secrets.compare_digest(supplied, settings.AUTH_TOKEN):
            return JSONResponse(
                status_code=401,
                content={"detail": "AUTH_TOKEN required: send 'Authorization: Bearer <token>'"},
            )
    return await call_next(request)


# ---------------------------------------------------------------- static ----


@app.get("/")
def index():
    page = WEBUI_DIR / "index.html"
    if not page.exists():
        return JSONResponse(
            status_code=503,
            content={
                "detail": "web UI not built — run `npm ci && npm run build` in frontend/ "
                          "(the built assets are gitignored on purpose)",
            },
        )
    return FileResponse(page)


if (WEBUI_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=WEBUI_DIR / "assets"), name="assets")


# ---------------------------------------------------------------- doctor ----


@app.get("/api/doctor")
def api_doctor(deep: bool = Query(False, description="actually launch Chromium (~1s)")):
    return doctor.run_checks(settings, deep=deep).as_dict()


# ------------------------------------------------------------------ runs ----


@app.get("/api/runs")
def api_runs():
    """Newest first. `out/` is the source of truth; this is a directory read."""
    return {"runs": [s.model_dump() for s in runrecord.scan(settings.OUT_DIR)]}


def _run_dir(run_id: str) -> Path:
    """Resolve a run id to a directory, refusing anything that escapes OUT_DIR.

    The id comes from a URL. Without this, `../../.ssh` is a valid run id.
    """
    root = settings.OUT_DIR.resolve()
    target = (root / run_id).resolve()
    if not target.is_dir() or root not in target.parents:
        raise HTTPException(status_code=404, detail=f"no such run: {run_id}")
    return target


# Declared before /api/runs/{run_id}: FastAPI matches routes in declaration order, so the
# literal path has to win before the parameterised one swallows "current" as an id.
@app.get("/api/runs/current")
def api_current(since: int = Query(0, ge=0, description="index into the event log")):
    job = runner.current
    if job is None:
        return {"idle": True}
    return {"idle": False, **job.snapshot(since=since)}


@app.post("/api/runs/current/cancel")
def api_cancel():
    if not runner.cancel():
        raise HTTPException(status_code=409, detail="no run in progress")
    return {"cancel_requested": True}


@app.get("/api/runs/{run_id}")
def api_run(run_id: str):
    directory = _run_dir(run_id)
    record = runrecord.read_json(directory)
    if record is None:
        # A run from before run.json existed. Still real, still has its PDFs.
        return {"legacy": True, **runrecord.summarize(directory).model_dump()}
    return record


@app.get("/api/runs/{run_id}/files/{name}")
def api_run_file(run_id: str, name: str):
    directory = _run_dir(run_id)
    if name not in {p.name for p in directory.iterdir() if p.is_file()}:
        raise HTTPException(status_code=404, detail=f"no such file in {run_id}: {name}")
    path = directory / name
    media = {"pdf": "application/pdf", "json": "application/json", "md": "text/markdown"}
    return FileResponse(
        path,
        media_type=media.get(path.suffix.lstrip("."), "application/octet-stream"),
        # inline so the browser renders the PDF rather than downloading it
        headers={"Content-Disposition": f'inline; filename="{name}"'},
    )


# -------------------------------------------------------------- analysis ----


class AnalyzeRequest(BaseModel):
    jd: str = Field(min_length=1)


@app.post("/api/analyze")
def api_analyze(request: AnalyzeRequest):
    """What this posting asks for and how far the record can get — before spending anything.

    Deliberately free. It runs jd.parse_deterministic (the lexicon pass, no model) and
    score.ceiling (the record and the posting, no model), so pasting a posting costs nothing
    and answers the question people actually open the tool with: *is this one worth
    applying to, and what will it say I am missing?*

    Running the full loop to find that out costs money and a minute, and the answer to "the
    posting wants three things your record has never contained" does not improve for having
    been paid for.
    """
    job = jd_module.parse_deterministic(request.jd)
    try:
        profile = load_profile(settings.PROFILE_PATH)
    except ProfileError as exc:
        raise HTTPException(status_code=412, detail=str(exc)) from exc

    index = source_index(profile, evidence.load(settings.EVIDENCE_PATH))
    limit = score_module.ceiling(profile, job, index)
    haystack = score_module.record_text(profile, index)
    unreachable = {t.casefold() for t in limit.unreachable}
    covered = [
        term for term in dict.fromkeys([*job.hard_skills, *job.keywords])
        if term.casefold() not in unreachable and contains_term(haystack, term)
    ]

    return {
        # Marked so the UI can say "no model was asked" rather than implying the LLM pass
        # (which fills in a title the lexicon missed, and adds keywords) already happened.
        "deterministic": True,
        "jd": runrecord.job_record(job).model_dump(),
        "ceiling": {
            "total": limit.total,
            "components": limit.components,
            "unreachable": limit.unreachable,
            "threshold": settings.SCORE_THRESHOLD,
            "reachable": limit.is_reachable(settings.SCORE_THRESHOLD),
        },
        "covered": covered,
    }


# ------------------------------------------------------------- execution ----


class RunRequest(BaseModel):
    # Paste only, by design: no upload endpoint means no multipart, no PDF sniffing, and
    # no server-side fetch of a user-supplied URL.
    jd: str = Field(min_length=1)
    mode: str = "both"
    threshold: float | None = None
    max_iter: int | None = None
    pages: int | None = None
    strict: bool = False


def _settings_for(request: RunRequest):
    overrides = {
        "SCORE_THRESHOLD": request.threshold,
        "MAX_ITER": request.max_iter,
        "RESUME_MAX_PAGES": request.pages,
        "STRICT_SCORE": True if request.strict else None,
    }
    return settings.model_copy(update={k: v for k, v in overrides.items() if v is not None})


def _work(request: RunRequest, cfg) -> Callable[[JobState], None]:
    """Build the closure the worker thread runs. Everything blocking happens in here."""

    def job(state: JobState) -> None:
        def call(system: str, user: str) -> dict:
            return llm.complete_json(system, user, cfg=cfg)

        progress = Progress(sink=state.report, cancel=state.cancel_event)

        progress(PARSING_JD)
        job_desc = jd_module.parse(request.jd, call)
        corpus = evidence.load(cfg.EVIDENCE_PATH)
        out_dir = run_dir(job_desc, cfg)
        state.set(run_id=out_dir.name, out_dir=str(out_dir))

        result = run(
            load_profile(cfg.PROFILE_PATH), job_desc, corpus, cfg, call,
            out_dir=out_dir, mode=request.mode, progress=progress,
        )
        state.set(ok=result.ok, cancelled=result.cancelled)

    return job


@app.post("/api/runs", status_code=202)
def api_start_run(request: RunRequest):
    if request.mode not in MODES:
        raise HTTPException(status_code=422, detail=f"mode must be one of {MODES}")

    report = doctor.run_checks(settings)
    if not report.ok:
        # Fail before spending an LLM call on a run that cannot finish. The UI blocks the
        # form on the same checks; this is the server refusing to be talked into it anyway.
        raise HTTPException(
            status_code=412,
            detail={"detail": "setup incomplete", "checks": [c.as_dict() for c in report.problems]},
        )
    try:
        load_profile(settings.PROFILE_PATH)
    except ProfileError as exc:
        raise HTTPException(status_code=412, detail=str(exc)) from exc

    cfg = _settings_for(request)
    try:
        state = runner.start(_work(request, cfg), mode=request.mode)
    except Busy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return state.snapshot()
