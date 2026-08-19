"""resume-fill — command surface (PLAN.md §6).

    resume-fill init              bootstrap profile.yaml from a LinkedIn export + résumé PDF
    resume-fill blog sync         refresh the evidence corpus from BLOG_URL
    resume-fill gen               job description -> tailored, grounded, verified PDFs
    resume-fill linkedin draft    proposed profile copy + diff vs current
    resume-fill serve             the same generate loop, in a browser
    resume-fill doctor            check config, sources and the PDF toolchain

Handlers import their stage modules lazily so `doctor` still runs on a half-installed
environment — which is exactly when you need it.
"""

import argparse
import sys
from datetime import date
from pathlib import Path

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


# ------------------------------------------------------------------ init ----


def cmd_init(args: argparse.Namespace) -> int:
    from .bootstrap import audit, bootstrap
    from .config import DATA_HOME, settings
    from .profile import dump_profile

    out_path = Path(args.out) if args.out else settings.PROFILE_PATH
    if out_path.exists() and not args.force:
        print(f"{BAD} {out_path} already exists. Re-run with --force to overwrite it.")
        print(f"{INFO} it is hand-corrected by design - overwriting throws those corrections away.")
        return 1

    export_dir = Path(args.linkedin_export) if args.linkedin_export else settings.LINKEDIN_EXPORT_DIR
    resume_path = Path(args.resume_pdf) if args.resume_pdf else _lone_pdf(DATA_HOME)

    print("== resume-fill init ==")
    if not export_dir.is_dir():
        print(f"{WARN} no LinkedIn export at {export_dir}")
        print("     Request one at linkedin.com/mypreferences/d/download-my-data, unpack it there.")
    if resume_path is None:
        print(f"{WARN} no résumé PDF given (--resume-pdf) and none found next to the project")

    try:
        profile, used, notes = bootstrap(export_dir if export_dir.is_dir() else None, resume_path)
    except RuntimeError as exc:
        print(f"{BAD} {exc}")
        return 1

    for line in used:
        print(f"{OK} read {line}")
    dump_profile(
        profile,
        out_path,
        note="Seeded by `resume-fill init`. Correct it by hand - every bullet here is\n"
        "quotable by the tailor, and nothing outside this file (plus the blog evidence\n"
        "corpus) can appear in a generated résumé.",
    )
    print(f"{OK} wrote {out_path}")

    todo = notes + audit(profile)
    if todo:
        print(f"\n{INFO} {len(todo)} thing(s) to check before generating anything:")
        for item in todo:
            print(f"     - {item}")
    else:
        print(f"{OK} nothing obviously missing - still worth reading once")
    return 0


def _lone_pdf(directory: Path) -> Path | None:
    """Use a PDF sitting next to the project only if there is exactly one; picking between
    two résumés is not a guess this should make silently."""
    pdfs = sorted(p for p in directory.glob("*.pdf") if p.is_file())
    return pdfs[0] if len(pdfs) == 1 else None


# ------------------------------------------------------------------ blog ----


def cmd_blog_sync(args: argparse.Namespace) -> int:
    from . import evidence
    from .config import settings
    from .ingest import blog

    blog_url = args.url or settings.BLOG_URL
    if not blog_url:
        print(f"{BAD} no blog to read. Set BLOG_URL in .env, or pass --url.")
        return 1

    print("== resume-fill blog sync ==")
    print(f"{INFO} {blog_url}")
    fetch = blog.http_fetcher(settings.BLOG_USER_AGENT)
    try:
        corpus, note = blog.sync(blog_url, fetch, max_posts=settings.BLOG_MAX_POSTS)
    except ValueError as exc:
        print(f"{BAD} {exc}")
        return 1

    if not corpus.items:
        print(f"{WARN} nothing found ({note}). The tool works without a blog - the corpus")
        print("     only ever adds specifics to bullets that profile.yaml already supports.")
        return 1

    evidence.save(corpus, settings.EVIDENCE_PATH)
    print(f"{OK} {note}")
    print(f"{OK} wrote {settings.EVIDENCE_PATH}")
    for item in corpus.items[:5]:
        print(f"     {item.id}  {item.title[:60]}")
    if len(corpus.items) > 5:
        print(f"     ... and {len(corpus.items) - 5} more")
    return 0


# -------------------------------------------------------------- linkedin ----


def cmd_linkedin_draft(args: argparse.Namespace) -> int:
    from . import evidence, linkedin_draft, llm
    from .config import settings
    from .profile import ProfileError, load_profile

    if not settings.llm_configured:
        print(f"{BAD} {llm.LLMNotConfigured()}")
        return 1
    try:
        profile = load_profile(settings.PROFILE_PATH)
    except ProfileError as exc:
        print(f"{BAD} {exc}")
        return 1

    export_dir = Path(args.export) if args.export else settings.LINKEDIN_EXPORT_DIR
    corpus = evidence.load(settings.EVIDENCE_PATH)

    print("== resume-fill linkedin draft ==")
    print(f"{INFO} LinkedIn has no public write API for profile fields, and automating the live")
    print("     account violates the User Agreement §8.2. This prints copy; you paste it.")
    if not export_dir.is_dir():
        print(f"{WARN} no LinkedIn export at {export_dir} - diffing against profile.yaml instead,")
        print("     which `init` may already have improved on. The diff will understate the change.")

    try:
        result = linkedin_draft.write(
            profile, corpus, settings, lambda s, u: llm.complete_json(s, u, cfg=settings),
            export_dir=export_dir if export_dir.is_dir() else None,
        )
    except llm.LLMError as exc:
        print(f"{BAD} {exc}")
        return 1

    body = linkedin_draft.render(result, profile)
    out_path = Path(args.out) if args.out else settings.OUT_DIR / f"linkedin-draft-{date.today()}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(body, encoding="utf-8")

    print()
    print(body)
    print(f"{INFO} written to {out_path}")
    if not result.ok:
        print(f"{BAD} the grounding gate rejected the draft - do not paste it as-is")
        return 1
    return 0


# ------------------------------------------------------------------- gen ----


def cmd_gen(args: argparse.Namespace) -> int:
    from . import evidence, llm
    from . import jd as jd_module
    from .config import settings
    from .pipeline import run, run_dir
    from .profile import ProfileError, load_profile
    from .progress import Progress
    from .render import RenderError

    cfg = settings.model_copy(
        update={
            k: v
            for k, v in {
                "MAX_ITER": args.max_iter,
                "SCORE_THRESHOLD": args.threshold,
                "RESUME_MAX_PAGES": args.pages,
                "STRICT_SCORE": True if args.strict else None,
            }.items()
            if v is not None
        }
    )

    if not cfg.llm_configured:
        print(f"{BAD} {llm.LLMNotConfigured()}")
        return 1
    try:
        profile = load_profile(cfg.PROFILE_PATH)
    except ProfileError as exc:
        print(f"{BAD} {exc}")
        return 1

    try:
        posting = jd_module.read_input(args.jd, user_agent=cfg.BLOG_USER_AGENT)
    except (OSError, ValueError) as exc:
        print(f"{BAD} {exc}")
        return 1

    job = jd_module.parse(posting, lambda s, u: llm.complete_json(s, u, cfg=cfg))
    corpus = evidence.load(cfg.EVIDENCE_PATH)
    out_dir = Path(args.out) if args.out else run_dir(job, cfg)
    mode = "cover" if args.cover else ("resume" if args.resume else "both")

    print("== resume-fill gen ==")
    print(f"{INFO} posting: {job.summary_line()}")
    print(f"{INFO} record:  {len(profile.experience)} roles, {len(profile.projects)} projects, "
          f"{len(corpus.items)} evidence items")
    print(f"{INFO} mode:    {mode}")
    print(f"{INFO} output:  {out_dir}")

    try:
        result = run(
            profile, job, corpus, cfg,
            lambda s, u: llm.complete_json(s, u, cfg=cfg),
            out_dir=out_dir, mode=mode, progress=Progress(sink=_stage_line),
        )
    except (llm.LLMError, RenderError) as exc:
        print(f"{BAD} {exc}")
        return 1

    print()
    code = 0
    if result.resume is not None:
        code |= _report_resume(result.resume, cfg)
    if result.cover is not None:
        code |= _report_cover(result.cover)
    print(f"{INFO} report: {result.report_path}")
    if result.record_path:
        print(f"{INFO} record: {result.record_path}")
    if result.cancelled:
        print(f"{WARN} the run was cancelled; what completed before then was kept")
        return 1
    return 1 if code else 0


_STAGE_LABEL = {
    "tailoring": "writing",
    "grounding": "checking every claim",
    "repaired": "kept what could be supported, cut the rest",
    "rejected": "rejected",
    "rendering": "rendering PDF",
    "verifying": "reading the PDF back",
    "scoring": "scoring",
    "scored": "done",
    "writing_report": "writing the report",
    "done": "finished",
    "cancelled": "cancelled",
}


def _stage_line(stage: str, detail: dict) -> None:
    """One line per stage. The CLI used to print a line per *attempt*, which meant up to a
    minute of silence between them — fine on a terminal, and the reason the UI needed this
    to exist at all."""
    label = _STAGE_LABEL.get(stage, stage)
    where = ""
    if "attempt" in detail:
        doc = "résumé" if detail.get("document") == "resume" else "cover letter"
        where = f"[{doc} {detail['attempt']}/{detail['attempts']}] "
    extra = {k: v for k, v in detail.items() if k not in ("document", "attempt", "attempts")}
    tail = "  " + ", ".join(f"{k} {v}" for k, v in extra.items()) if extra else ""
    print(f"  {where}{label}{tail}", flush=True)


def _report_cover(cover_run) -> int:
    best = cover_run.best
    if best.violations:
        print(f"{BAD} the grounding gate rejected every cover letter - no PDF was written")
        for violation in best.violations[:10]:
            print(f"     - [{violation.kind}] {violation}")
        return 1
    letter = best.document
    print(f"{OK} {best.rendered.pdf_path}")
    print(f"{INFO} {letter.word_count()} words, {len(letter.paragraphs)} paragraphs, "
          f"addressed to {letter.addressee}")
    if best.repair is not None and best.repair.dropped:
        print(f"{WARN} {len(best.repair.dropped)} paragraph(s) removed - they claimed more "
              "than the record supports")
    if cover_run.blocked_terms:
        print(f"{INFO} the gate blocked these claims: " + ", ".join(cover_run.blocked_terms[:12]))
    if not cover_run.ok:
        print(f"{BAD} the cover letter PDF did not survive its own parse check")
        return 1
    return 0


def _report_resume(result, cfg) -> int:
    """Exit code policy (PLAN.md open question 5, resolved).

    A PDF that does not parse is a build failure, always — that is the one guarantee this
    tool makes. A score that does not clear the threshold is *not* a failure by default:
    the gate stopped the loop inflating it, so a low ceiling is the honest answer and the
    report says which experience the role wants that you do not have. STRICT_SCORE turns
    it into a failure for anyone who wants the loop to be a hard gate.
    """
    best = result.best
    if best.violations:
        print(f"{BAD} the grounding gate rejected every résumé attempt - no PDF was written")
        for violation in best.violations[:10]:
            print(f"     - [{violation.kind}] {violation}")
        return 1

    print(f"{OK} {best.rendered.pdf_path}")
    if best.repair is not None and best.repair.dropped:
        # Not a failure and not silent either: the résumé is smaller than the model drafted,
        # and the difference is the list of things the record could not back.
        print(f"{WARN} {len(best.repair.dropped)} item(s) cut to keep every claim supported:")
        for note in best.repair.notes()[:6]:
            print(f"     - {note}")
    print(f"{INFO} {best.verify_report.summary()}")
    print(
        f"{INFO} score {best.total:.1f} of a reachable {result.reachable:.1f} "
        f"(threshold {result.threshold:.0f}) - stopped because {result.why_stopped()}"
    )
    for component in best.score.components:
        print(f"       {component.points:5.1f}  {component.label} - {component.detail}")

    real = best.score.real_gaps()
    if real:
        print(f"{INFO} not in your record, deliberately left out: "
              + ", ".join(g.keyword for g in real[:12]))
    if result.blocked_terms:
        print(f"{INFO} the gate blocked these claims: " + ", ".join(result.blocked_terms[:12]))

    if not result.ok:
        print(f"{BAD} the PDF did not survive its own parse check - fix before sending")
        return 1
    if result.met_threshold:
        return 0
    if not result.threshold_reachable:
        # The threshold was never available to this record. Calling that a failure - even
        # under STRICT_SCORE - would be scoring the candidate on experience they were never
        # claimed to have, which is the one thing this tool exists not to do.
        print(
            f"{INFO} the threshold of {result.threshold:.0f} was not reachable for this record: "
            f"this posting caps at {result.reachable:.1f}. "
            + (
                "Out of reach: " + ", ".join(result.ceiling.unreachable[:8])
                if result.ceiling and result.ceiling.unreachable
                else ""
            )
        )
        return 0
    message = (
        f"score is below the threshold ({best.total:.1f} < {result.threshold:.0f}), and "
        f"{result.reachable:.1f} was reachable - this one is tailoring, not the record"
    )
    if cfg.STRICT_SCORE:
        print(f"{BAD} {message}; STRICT_SCORE is on")
        return 1
    print(f"{WARN} {message}. See the unsurfaced keywords in report.md.")
    return 0


# ---------------------------------------------------------------- doctor ----


def cmd_doctor(args: argparse.Namespace) -> int:
    from . import doctor
    from .config import DATA_HOME, settings

    print("== resume-fill doctor ==")
    print(f"   data home: {DATA_HOME}")
    # Deep: actually launch Chromium. The API's preflight settles for checking the
    # executable exists, because it runs on every page load; this runs when you asked.
    report = doctor.run_checks(settings, deep=True)

    for check in report.checks:
        mark = OK if check.ok else (BAD if check.blocking else WARN)
        print(f"{mark} {check.name}: {check.detail}")
        if not check.ok and check.fix:
            print(f"     fix: {check.fix}")

    print()
    if report.ok:
        print(f"{OK} no blocking problems")
        return 0
    print(f"{BAD} {len(report.problems)} blocking problem(s)")
    return 1


# ----------------------------------------------------------------- serve ----


def cmd_serve(args: argparse.Namespace) -> int:
    import webbrowser

    from .config import settings
    from .main import WEBUI_DIR, app, check_bind_security

    host = args.host or settings.HOST
    port = args.port or settings.PORT
    try:
        check_bind_security(host, settings.AUTH_TOKEN)
    except RuntimeError as exc:
        print(f"{BAD} {exc}")
        return 1

    # The middleware reads settings.HOST to decide whether the bind is local, so a --host
    # override has to land there too or the guard would be checking the wrong address.
    settings.HOST = host

    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{port}/"
    print("== resume-fill serve ==")
    print(f"{INFO} {url}")
    if not (WEBUI_DIR / "index.html").exists():
        print(f"{WARN} web UI not built - run `npm ci && npm run build` in frontend/")
        print(f"     ({WEBUI_DIR} is gitignored on purpose; the JSON API works regardless)")
    if not args.no_open:
        webbrowser.open(url)

    import uvicorn

    # The app object rather than an import string: uvicorn would otherwise re-import the
    # module and get a fresh settings instance that never saw the --host override.
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0


# ------------------------------------------------------------------ main ----


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="resume-fill",
        description="Job-specific, evidence-grounded résumés and cover letters.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="bootstrap profile.yaml from a LinkedIn export + résumé PDF")
    p_init.add_argument("--linkedin-export", metavar="DIR", help="unpacked LinkedIn data archive")
    p_init.add_argument("--resume-pdf", metavar="FILE", help="an existing résumé to lift bullets from")
    p_init.add_argument("--out", metavar="PATH", help="where to write (default: profile.yaml)")
    p_init.add_argument("--force", action="store_true", help="overwrite an existing profile.yaml")
    p_init.set_defaults(func=cmd_init)

    p_blog = sub.add_parser("blog", help="the blog-derived evidence corpus")
    blog_sub = p_blog.add_subparsers(dest="blog_command", required=True)
    p_sync = blog_sub.add_parser("sync", help="refresh data/evidence.json from BLOG_URL")
    p_sync.add_argument("--url", metavar="URL", help="override BLOG_URL for this run")
    p_sync.set_defaults(func=cmd_blog_sync)

    p_linkedin = sub.add_parser("linkedin", help="LinkedIn profile copy (draft only - you paste it)")
    linkedin_sub = p_linkedin.add_subparsers(dest="linkedin_command", required=True)
    p_draft = linkedin_sub.add_parser("draft", help="proposed headline/About/experience + diff")
    p_draft.add_argument("--export", metavar="DIR", help="LinkedIn export, to diff against the live copy")
    p_draft.add_argument("--out", metavar="FILE", help="where to write the draft")
    p_draft.set_defaults(func=cmd_linkedin_draft)

    p_gen = sub.add_parser("gen", help="job description -> tailored, grounded, verified résumé PDF")
    p_gen.add_argument("--jd", required=True, metavar="SOURCE",
                       help="job description: a file path, an https URL, or - for stdin")
    mode = p_gen.add_mutually_exclusive_group()
    mode.add_argument("--resume", action="store_true", help="résumé only")
    mode.add_argument("--cover", action="store_true", help="cover letter only")
    mode.add_argument("--both", action="store_true", help="both (the default)")
    p_gen.add_argument("--out", metavar="DIR", help="output directory (default: out/<company>-<role>-<date>)")
    p_gen.add_argument("--max-iter", type=int, metavar="N", help="rewrite attempts (default: MAX_ITER)")
    p_gen.add_argument("--threshold", type=float, metavar="N", help="stop at this score (default: SCORE_THRESHOLD)")
    p_gen.add_argument("--pages", type=int, metavar="N", help="page budget (default: RESUME_MAX_PAGES)")
    p_gen.add_argument("--strict", action="store_true",
                       help="fail the run when the score stays below the threshold")
    p_gen.set_defaults(func=cmd_gen)

    p_serve = sub.add_parser("serve", help="run the local web UI")
    p_serve.add_argument("--host", metavar="ADDR", help=f"bind address (default: {'127.0.0.1'})")
    p_serve.add_argument("--port", type=int, metavar="N", help="port (default: 8765)")
    p_serve.add_argument("--no-open", action="store_true", help="do not open a browser")
    p_serve.set_defaults(func=cmd_serve)

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
