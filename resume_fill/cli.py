"""resume-fill — command surface.

    resume-fill doctor    check config, sources and the PDF toolchain

Later milestones add `init`, `blog sync`, `gen` and `linkedin draft` (PLAN.md §6).
Handlers import their stage modules lazily so `doctor` still runs on a half-installed
environment — which is exactly when you need it.
"""

import argparse
import sys

OK = "[ok]"
BAD = "[!!]"
WARN = "[??]"
INFO = "[--]"


def _force_utf8_stdout() -> None:
    """Windows consoles default to a legacy codepage, and this tool prints names,
    accented words and diff output straight from the profile. Without this, `init` on a
    profile containing "José" dies with UnicodeEncodeError instead of printing it."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


# ---------------------------------------------------------------- doctor ----


def cmd_doctor(args: argparse.Namespace) -> int:
    from .config import DATA_HOME, settings

    problems = 0
    print("== resume-fill doctor ==")
    print(f"   data home: {DATA_HOME}")

    if settings.llm_configured:
        print(f"{OK} LLM configured: {settings.LLM_MODEL} @ {settings.LLM_BASE_URL}")
    else:
        problems += 1
        print(f"{BAD} LLM not configured - copy .env.example to .env and set LLM_API_KEY/BASE_URL/MODEL")

    if settings.PROFILE_PATH.exists():
        print(f"{OK} profile: {settings.PROFILE_PATH}")
    else:
        print(f"{WARN} no profile yet at {settings.PROFILE_PATH} - run `resume-fill init`")

    if settings.EVIDENCE_PATH.exists():
        print(f"{OK} evidence corpus: {settings.EVIDENCE_PATH}")
    else:
        print(f"{WARN} no evidence corpus - run `resume-fill blog sync` (needs BLOG_URL)")

    problems += _check_pdf_toolchain()
    print()
    print(f"{OK} no blocking problems" if not problems else f"{BAD} {problems} blocking problem(s)")
    return 1 if problems else 0


def _check_pdf_toolchain() -> int:
    """Playwright's bundled Chromium is the whole PDF story — this machine has no Word,
    LibreOffice, pandoc, Typst or LaTeX (PLAN.md §2), so a missing browser is fatal."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(f"{BAD} playwright not installed - run `uv sync`")
        return 1
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            browser.close()
    except Exception as exc:
        print(f"{BAD} Chromium not usable ({type(exc).__name__}) - run `uv run playwright install chromium`")
        return 1
    print(f"{OK} Playwright Chromium available (PDF renderer)")

    try:
        import pdfminer  # noqa: F401
    except ImportError:
        print(f"{BAD} pdfminer.six not installed - run `uv sync`")
        return 1
    print(f"{OK} pdfminer.six available (PDF round-trip verifier)")
    return 0


# ------------------------------------------------------------------ main ----


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="resume-fill",
        description="Job-specific, evidence-grounded résumés and cover letters.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_doctor = sub.add_parser("doctor", help="check config, sources and the PDF toolchain")
    p_doctor.set_defaults(func=cmd_doctor)

    return parser


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdout()
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
