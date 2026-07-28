from pathlib import Path

import pytest

from resume_fill.profile import load_profile

REPO_ROOT = Path(__file__).resolve().parents[1]


def chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False
    try:
        with sync_playwright() as p:
            p.chromium.launch().close()
        return True
    except Exception:
        return False


needs_chromium = pytest.mark.skipif(
    not chromium_available(), reason="needs `playwright install chromium`"
)


@pytest.fixture(scope="session")
def html_to_pdf(tmp_path_factory):
    """Render HTML to a real PDF with the same engine the tool ships with.

    Tests that parse PDFs have to parse *real* ones: the whole point of the round-trip
    assertion is that a PDF's text layer is not its markup.
    """
    from playwright.sync_api import sync_playwright

    directory = tmp_path_factory.mktemp("pdfs")

    def render(html: str, name: str) -> Path:
        out = directory / name
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.set_content(html)
            page.emulate_media(media="print")
            page.pdf(
                path=str(out), format="Letter", print_background=True,
                margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
            )
            browser.close()
        return out

    return render


@pytest.fixture
def example_profile():
    """profile.example.yaml is the committed shape of the canonical record, so every test
    that needs a realistic profile uses it — which also keeps the example honest."""
    return load_profile(REPO_ROOT / "profile.example.yaml")


@pytest.fixture
def linkedin_export(tmp_path: Path) -> Path:
    """A minimal but faithful LinkedIn data archive: BOM, the columns LinkedIn actually
    ships, and the "Notes:" preamble older archives put above the header."""
    export = tmp_path / "linkedin_export"
    export.mkdir()

    def write(name: str, text: str) -> None:
        (export / name).write_text(text, encoding="utf-8-sig")

    write(
        "Profile.csv",
        'First Name,Last Name,Headline,Geo Location,Websites\n'
        'Ada,Lovelace,Backend engineer,"Brooklyn, New York",PERSONAL:(https://example.com)\n',
    )
    write("Email Addresses.csv", "Email Address,Confirmed,Primary\nold@example.com,Yes,No\nada@example.com,Yes,Yes\n")
    write("PhoneNumbers.csv", "Extension,Number,Type\n,(555) 010-1990,MOBILE\n")
    write(
        "Positions.csv",
        "Notes:\n"
        '"When exported, this file contains your positions."\n'
        "Company Name,Title,Description,Location,Started On,Finished On\n"
        'Northwind Analytics,Backend Engineer Intern,"Rewrote the nightly ingestion job.\n'
        'Added contract tests.","New York, NY",Jun 2025,Aug 2025\n'
        "Hunter College IT,Student Technician,,\"New York, NY\",Sep 2024,May 2025\n",
    )
    write(
        "Education.csv",
        "School Name,Start Date,End Date,Notes,Degree Name\n"
        '"Hunter College, CUNY",2023,2027,,B.A. Computer Science\n',
    )
    write("Skills.csv", "Name\nPython\nPostgreSQL\n")
    write(
        "Projects.csv",
        "Title,Description,Url,Started On,Finished On\n"
        "tidepool,Offline tide tables.,https://github.com/example/tidepool,Jan 2025,\n",
    )
    write(
        "Certifications.csv",
        "Name,Url,Authority,Started On,Finished On,License Number\n"
        "AWS Certified Cloud Practitioner,,Amazon Web Services,Mar 2025,,\n",
    )
    return export
