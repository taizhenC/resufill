import pytest

from resume_fill.jd import (
    JobDescription,
    enrich,
    parse,
    parse_deterministic,
    read_input,
    strip_html,
)

POSTING = """\
Backend Engineer, Data Platform
Northwind Analytics — New York, NY (Hybrid)

About the role
You will own the ingestion path end to end and keep it boring.

Responsibilities
- Build and operate batch and streaming pipelines
- Partner with analysts on data modelling

Basic Qualifications
- 3+ years writing production Python
- Strong SQL and experience with PostgreSQL
- Familiarity with Airflow or a comparable orchestrator

Preferred Qualifications
- Kubernetes in production
- Experience with Kafka
"""


def test_deterministic_parse_needs_no_model():
    """The lexicon pass is what lets `gen` read a posting with no API key configured at
    all — and it means the model can only ever add to the requirement set, never drop
    something the posting plainly asked for."""
    jd = parse_deterministic(POSTING)

    assert jd.title == "Backend Engineer, Data Platform"
    assert jd.seniority == ""
    assert jd.min_years == 3
    assert {"Python", "SQL", "PostgreSQL", "Airflow", "Kubernetes", "Kafka"} <= set(jd.hard_skills)


def test_requirements_and_responsibilities_land_in_different_buckets():
    jd = parse_deterministic(POSTING)
    assert "Build and operate batch and streaming pipelines" in jd.responsibilities
    assert "3+ years writing production Python" in jd.qualifications
    assert "Kubernetes in production" in jd.qualifications
    assert "Build and operate batch and streaming pipelines" not in jd.qualifications


def test_unlabelled_bullets_are_treated_as_requirements():
    """Under-reporting a requirement is the damaging direction: it becomes a gap the
    report never mentions."""
    jd = parse_deterministic("Widget Engineer\n\n- Must know Rust\n- Must know Docker\n")
    assert jd.qualifications == ["Must know Rust", "Must know Docker"]


def test_seniority_comes_from_the_title_not_the_body():
    """Postings say "you will work with senior engineers" in the body all the time."""
    jd = parse_deterministic("Software Engineer Intern\n\nYou will pair with senior engineers.\n")
    assert jd.seniority == "intern"


def test_company_is_found_from_an_about_heading():
    assert parse_deterministic("Engineer\n\nAbout Northwind\nWe do data.\n").company == "Northwind"


def test_about_us_is_not_a_company_name():
    assert parse_deterministic("Engineer\n\nAbout Us\nWe do data.\n").company == ""
    assert parse_deterministic("Engineer\n\nAbout the role\nYou will build.\n").company == ""


def test_run_slug_is_filename_safe_and_still_recognisable():
    jd = JobDescription(raw="", title="Backend Engineer, Data Platform", company="Northwind Analytics")
    assert jd.run_slug == "northwind-analytics-backend-engineer-data-platform"


def test_strip_html_keeps_the_list_structure_a_posting_carries():
    text = strip_html(
        "<div><h2>Requirements</h2><ul><li>Python</li><li>SQL &amp; dbt</li></ul>"
        "<script>ignore()</script></div>"
    )
    assert "Requirements" in text
    assert "- Python" in text
    assert "- SQL & dbt" in text
    assert "ignore" not in text


def test_read_input_from_a_file(tmp_path):
    path = tmp_path / "jd.txt"
    path.write_text(POSTING, encoding="utf-8")
    assert read_input(str(path)).startswith("Backend Engineer")


def test_read_input_names_the_alternatives_when_the_path_is_wrong(tmp_path):
    with pytest.raises(FileNotFoundError, match="stdin"):
        read_input(str(tmp_path / "nope.txt"))


def test_read_input_from_stdin(monkeypatch):
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO(POSTING))
    assert read_input("-").startswith("Backend Engineer")


# ------------------------------------------------------------- LLM pass ----


def test_enrich_adds_what_the_lexicon_missed_and_keeps_what_it_found():
    jd = parse_deterministic(POSTING)
    before = list(jd.hard_skills)

    def fake(system, user):
        return {
            "title": "Something Else",  # must not overwrite a title we already found
            "company": "Northwind Analytics",
            "seniority": "mid",
            "hard_skills": ["dbt", "postgres"],  # one new, one a spelling variant
            "qualifications": ["Comfortable being on call"],
            "keywords": ["data platform"],
        }

    jd = enrich(jd, fake)
    assert jd.title == "Backend Engineer, Data Platform"
    assert jd.company == "Northwind Analytics"
    assert jd.seniority == "mid"
    assert jd.hard_skills[: len(before)] == before
    assert "dbt" in jd.hard_skills
    # "postgres" canonicalises onto the PostgreSQL the lexicon already found, so it does
    # not become a second, duplicate requirement.
    assert jd.hard_skills.count("PostgreSQL") == 1
    assert "Comfortable being on call" in jd.qualifications
    assert "data platform" in jd.keywords


def test_enrich_survives_an_unreachable_model():
    """A posting parsed by lexicon alone still generates a résumé. Dying here would make an
    unreachable endpoint fatal to the whole tool."""
    from resume_fill.llm import LLMError

    def broken(system, user):
        raise LLMError("connection refused")

    jd = parse(POSTING, broken)
    assert "Python" in jd.hard_skills


def test_enrich_ignores_a_model_that_returns_the_wrong_types():
    def sloppy(system, user):
        return {"hard_skills": "Python", "qualifications": None, "title": 42}

    jd = enrich(parse_deterministic(POSTING), sloppy)
    assert jd.title == "Backend Engineer, Data Platform"
    assert "Python" in jd.hard_skills
