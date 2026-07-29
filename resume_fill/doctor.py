"""Preflight checks, as data.

`doctor` was the only command that worked when nothing else did, and it earned that by
actually launching Chromium rather than checking a wheel was installed. Now the browser
needs the same answers, so the checks return structured results and the CLI is one renderer
of them rather than the only place they exist.

Two depths, because the cost differs by three orders of magnitude:

  - shallow: does the Chromium executable exist on disk? Microseconds. Enough for a page
    load, and it catches the failure that actually happens (`playwright install` never run).
  - deep: launch it and close it. About a second. What `resume-fill doctor` does, because
    a browser that is present but broken is worth finding before a deadline rather than
    during one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import Settings
from .config import settings as default_settings


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    # Blocking means generation cannot work at all. A missing evidence corpus is not
    # blocking: the tool is designed to work without a blog.
    blocking: bool = True
    fix: str = ""

    def as_dict(self) -> dict:
        return {
            "name": self.name, "ok": self.ok, "detail": self.detail,
            "blocking": self.blocking, "fix": self.fix,
        }


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Blocking failures only. Warnings are for the human, not for the gate."""
        return all(c.ok for c in self.checks if c.blocking)

    @property
    def problems(self) -> list[Check]:
        return [c for c in self.checks if not c.ok and c.blocking]

    @property
    def warnings(self) -> list[Check]:
        return [c for c in self.checks if not c.ok and not c.blocking]

    def as_dict(self) -> dict:
        return {"ok": self.ok, "checks": [c.as_dict() for c in self.checks]}


def _llm(cfg: Settings) -> Check:
    if cfg.llm_configured:
        return Check("llm", True, f"{cfg.LLM_MODEL} @ {cfg.LLM_BASE_URL}")
    return Check(
        "llm", False, "no API key, base URL or model configured",
        fix="copy .env.example to .env and set LLM_API_KEY, LLM_BASE_URL and LLM_MODEL",
    )


def _profile(cfg: Settings) -> Check:
    if cfg.PROFILE_PATH.exists():
        return Check("profile", True, str(cfg.PROFILE_PATH))
    return Check(
        "profile", False, f"no profile at {cfg.PROFILE_PATH}",
        fix="resume-fill init --linkedin-export data/linkedin_export --resume-pdf old-resume.pdf",
    )


def _evidence(cfg: Settings) -> Check:
    if cfg.EVIDENCE_PATH.exists():
        return Check("evidence", True, str(cfg.EVIDENCE_PATH), blocking=False)
    return Check(
        "evidence", False, "no blog evidence corpus",
        blocking=False,  # the tool is designed to work without one
        fix="resume-fill blog sync   (needs BLOG_URL; entirely optional)",
    )


def _chromium(deep: bool) -> Check:
    """Playwright's bundled Chromium is the whole PDF story — this machine has no Word,
    LibreOffice, pandoc, Typst or LaTeX (PLAN.md §2)."""
    fix = "uv run playwright install chromium"
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return Check("chromium", False, "playwright is not installed", fix="uv sync")
    try:
        with sync_playwright() as p:
            path = p.chromium.executable_path
            if not deep:
                from pathlib import Path

                exists = Path(path).exists()
                return Check(
                    "chromium", exists,
                    "browser present" if exists else "browser not downloaded", fix=fix,
                )
            p.chromium.launch().close()
    except Exception as exc:
        return Check("chromium", False, f"not usable ({type(exc).__name__})", fix=fix)
    return Check("chromium", True, "launches and closes cleanly")


def _pdfminer() -> Check:
    try:
        import pdfminer  # noqa: F401
    except ImportError:
        return Check("pdfminer", False, "pdfminer.six is not installed", fix="uv sync")
    return Check("pdfminer", True, "available (PDF round-trip verifier)")


def run_checks(cfg: Settings | None = None, *, deep: bool = False) -> Report:
    cfg = cfg or default_settings
    return Report(
        checks=[_llm(cfg), _profile(cfg), _evidence(cfg), _chromium(deep), _pdfminer()]
    )
