"""`resume.json` + `profile.yaml` -> HTML -> Chromium -> PDF.

Playwright's bundled Chromium is the whole rendering story: this machine has no Word,
LibreOffice, pandoc, Typst or LaTeX (PLAN.md §2), so the renderer has to bring its own
engine. HTML/CSS is what that engine speaks.

The important work here is not the layout, it is the resolution step: every company name,
job title and date is looked up in profile.yaml by the id the tailor selected. The model
never writes a fact, so a fact can never be wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jinja2 import ChoiceLoader, Environment, FileSystemLoader, StrictUndefined, TemplateNotFound
from markupsafe import Markup

from .config import Settings
from .document import ResumeDoc
from .profile import Profile

SECTION_TITLES = {
    "summary": "Summary",
    "skills": "Skills",
    "experience": "Experience",
    "projects": "Projects",
    "education": "Education",
    "certifications": "Certifications",
}


class RenderError(RuntimeError):
    """The document could not be turned into a PDF."""


@dataclass
class Rendered:
    pdf_path: Path
    html_path: Path
    page_count: int


def environment(cfg: Settings) -> Environment:
    """User templates first, packaged defaults second — so a checkout can replace one
    template without vendoring the rest."""
    loaders = [FileSystemLoader(str(d)) for d in cfg.template_dirs if d.exists()]
    if not loaders:
        raise RenderError(f"no template directory found (looked in {cfg.template_dirs})")
    return Environment(
        loader=ChoiceLoader(loaders), autoescape=True, undefined=StrictUndefined,
        trim_blocks=True, lstrip_blocks=True,
    )


# ------------------------------------------------------------- context ----


def _part(text: str, *, italic: bool = False) -> dict:
    return {"text": text, "italic": italic}


def _entry_context(entry, bullets: list[str], kind: str) -> dict:
    """One résumé entry, with its facts taken from the profile rather than the document."""
    if kind == "experience":
        parts = [_part(entry.title, italic=True), _part(entry.location), _part(entry.dates)]
    elif kind == "projects":
        parts = [_part(entry.url), _part(entry.dates)]
    else:
        degree = " ".join(p for p in (entry.degree, entry.field_of_study) if p)
        gpa = f"GPA {entry.gpa}" if entry.gpa else ""
        parts = [_part(degree, italic=True), _part(entry.location), _part(gpa), _part(entry.dates)]
    primary = entry.company if kind == "experience" else (
        entry.name if kind == "projects" else entry.institution
    )
    return {"primary": primary, "parts": [p for p in parts if p["text"]], "bullets": bullets}


def _entries_section(doc: ResumeDoc, profile: Profile, kind: str) -> dict | None:
    by_id = {
        e.id: e
        for e in {
            "experience": profile.experience,
            "projects": profile.projects,
            "education": profile.education,
        }[kind]
    }
    selected = {"experience": doc.experience, "projects": doc.projects, "education": doc.education}[kind]
    entries = []
    for chosen in selected:
        source = by_id.get(chosen.source_id)
        if source is None:
            # ground.py rejects this before render is ever reached; skipping rather than
            # raising keeps `--no-verify`-style debugging usable.
            continue
        entries.append(_entry_context(source, [b.text for b in chosen.bullets], kind))
    return {"kind": "entries", "title": SECTION_TITLES[kind], "entries": entries} if entries else None


def build_context(doc: ResumeDoc, profile: Profile, cfg: Settings, *, css: str = "") -> dict:
    sections: list[dict] = []
    for name in doc.ordered_sections():
        if name == "summary" and doc.summary.strip():
            sections.append({"kind": "summary", "title": SECTION_TITLES[name], "text": doc.summary.strip()})
        elif name == "skills":
            groups = [(label, ", ".join(items)) for label, items in doc.skills.items() if items]
            if groups:
                sections.append({"kind": "skills", "title": SECTION_TITLES[name], "groups": groups})
        elif name in ("experience", "projects", "education"):
            if section := _entries_section(doc, profile, name):
                sections.append(section)
        elif name == "certifications" and doc.certification_ids:
            by_id = {c.id: c for c in profile.certifications}
            items = [
                " | ".join(p for p in (by_id[cid].label, by_id[cid].date) if p)
                for cid in doc.certification_ids
                if cid in by_id
            ]
            if items:
                sections.append({"kind": "list", "title": SECTION_TITLES[name], "items": items})

    return {
        "name": profile.basics.name,
        "headline": doc.headline.strip() or profile.basics.headline,
        "contact": profile.basics.contact_line(),
        "sections": sections,
        "css": css,
        "page_format": cfg.PAGE_FORMAT,
        "margin_in": cfg.PAGE_MARGIN_IN,
    }


def render_html(doc: ResumeDoc, profile: Profile, cfg: Settings, *, template: str = "resume.html.j2") -> str:
    env = environment(cfg)
    try:
        css = env.get_template("resume.css").render(
            page_format=cfg.PAGE_FORMAT, margin_in=cfg.PAGE_MARGIN_IN, font_pt=cfg.FONT_PT
        )
        page = env.get_template(template)
    except TemplateNotFound as exc:
        raise RenderError(f"template not found: {exc.name}") from exc
    # Autoescape is on, and it must stay on — every other value in the context is profile
    # text. But escaping the stylesheet turns `font-family: "Helvetica Neue"` into
    # `font-family: &#34;Helvetica Neue&#34;`, which Chromium discards as invalid and
    # silently falls back to a serif default. The CSS comes from a template in this repo,
    # not from user input, so it is marked safe here rather than by weakening the template.
    context = build_context(doc, profile, cfg, css=Markup(css))
    context["font_pt"] = cfg.FONT_PT
    return page.render(**context)


# ----------------------------------------------------------------- pdf ----


def page_count(pdf_path: Path) -> int:
    from pdfminer.pdfpage import PDFPage

    with pdf_path.open("rb") as handle:
        return sum(1 for _ in PDFPage.get_pages(handle))


def html_to_pdf(html: str, out_path: Path, cfg: Settings) -> None:
    """Chromium, print media, CSS page size.

    set_content() loads the page with no base URL, which is why the stylesheet is inlined
    by the template: a <link> would resolve to nothing and the PDF would come out unstyled
    with no error anywhere.
    """
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise RenderError("playwright is not installed - run `uv sync`") from exc

    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page()
                page.set_content(html, wait_until="load")
                page.emulate_media(media="print")
                page.pdf(
                    path=str(out_path),
                    format=cfg.PAGE_FORMAT,
                    print_background=True,
                    prefer_css_page_size=True,
                )
            finally:
                browser.close()
    except PlaywrightError as exc:
        raise RenderError(
            f"Chromium could not render the PDF ({exc}). If it is not installed, run "
            "`uv run playwright install chromium`."
        ) from exc


def render_resume(
    doc: ResumeDoc, profile: Profile, out_dir: Path, cfg: Settings, *, stem: str = "resume"
) -> Rendered:
    html = render_html(doc, profile, cfg)
    html_path = out_dir / f"{stem}.html"
    pdf_path = out_dir / f"{stem}.pdf"
    out_dir.mkdir(parents=True, exist_ok=True)
    # Kept next to the PDF: when a bullet fails the round-trip assertion, the first
    # question is always whether it made it into the HTML.
    html_path.write_text(html, encoding="utf-8")
    html_to_pdf(html, pdf_path, cfg)
    return Rendered(pdf_path=pdf_path, html_path=html_path, page_count=page_count(pdf_path))
