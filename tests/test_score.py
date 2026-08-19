from resume_fill.document import Bullet, ResumeDoc, SelectedEntry
from resume_fill.jd import JobDescription, parse_deterministic
from resume_fill.score import WEIGHTS, addresses, classify_gaps, feedback, score
from resume_fill.verify import VerifyReport

POSTING = parse_deterministic(
    "Backend Engineer\n\n"
    "Basic Qualifications\n"
    "- Production Python\n"
    "- Strong PostgreSQL\n"
    "- Kubernetes in production\n"
)


def _doc(**kwargs) -> ResumeDoc:
    base = dict(
        experience=[
            SelectedEntry(
                source_id="exp-northwind-backend",
                bullets=[
                    Bullet(
                        text="Rewrote the nightly ingestion job in Python against PostgreSQL.",
                        source_ids=["exp-northwind-backend.h1"],
                    )
                ],
            )
        ],
        skills={"Languages": ["Python"]},
    )
    base.update(kwargs)
    return ResumeDoc(**base)


def test_weights_are_the_ones_written_down_in_the_plan():
    """Not tuned until the output looked good — PLAN.md §4."""
    assert WEIGHTS == {
        "hard_skills": 0.40, "qualifications": 0.15, "title_fit": 0.15,
        "keywords_in_context": 0.20, "format": 0.10,
    }
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9


def test_total_is_the_sum_of_the_components(example_profile):
    result = score(_doc(), example_profile, POSTING, example_profile.sources())
    assert abs(result.total - sum(c.points for c in result.components)) < 0.05
    assert 0 <= result.total <= 100


def test_hard_skill_coverage_counts_what_the_posting_named(example_profile):
    result = score(_doc(), example_profile, POSTING, example_profile.sources())
    component = result.component("hard_skills")
    assert "Python" in result.matched and "PostgreSQL" in result.matched
    assert component.raw < 1.0  # Kubernetes is not there
    assert "of 3" in component.detail


def test_gaps_separate_a_tailoring_miss_from_a_fact_about_you(example_profile):
    """The distinction that makes the list worth reading. SQLite is in the record and did
    not get surfaced; Kubernetes is nowhere and no rewrite can close it."""
    jd = JobDescription(raw="", hard_skills=["Kubernetes", "SQLite"], keywords=["Kubernetes", "SQLite"])
    result = score(_doc(), example_profile, jd, example_profile.sources())

    assert [g.keyword for g in result.real_gaps()] == ["Kubernetes"]
    unsurfaced = result.unsurfaced()
    assert [g.keyword for g in unsurfaced] == ["SQLite"]
    assert unsurfaced[0].where  # names where in the record it lives


def test_classify_gaps_finds_a_term_recorded_only_as_a_highlight_skill(example_profile):
    gaps = classify_gaps(["asyncio"], example_profile.sources())
    assert gaps[0].in_record and gaps[0].where


def test_keyword_coverage_ignores_the_skills_line(example_profile):
    """A skills line is free to write and carries no evidence. Counting it here would
    reward exactly the padding this component exists to discourage."""
    jd = JobDescription(raw="", keywords=["Docker"])
    listed_only = _doc(skills={"Tools": ["Docker"]})
    result = score(listed_only, example_profile, jd, example_profile.sources())
    assert result.component("keywords_in_context").raw == 0.0


def test_repeating_a_keyword_is_penalised(example_profile):
    jd = JobDescription(raw="", keywords=["Python"])
    stuffed = _doc(
        experience=[
            SelectedEntry(
                source_id="exp-northwind-backend",
                bullets=[
                    Bullet(text=f"Python work {i} in Python with Python.",
                           source_ids=["exp-northwind-backend.h1"])
                    for i in range(4)
                ],
            )
        ]
    )
    honest = _doc()
    result_stuffed = score(stuffed, example_profile, jd, example_profile.sources())
    result_honest = score(honest, example_profile, jd, example_profile.sources())
    assert result_stuffed.stuffed == ["Python"]
    assert result_stuffed.component("keywords_in_context").raw < result_honest.component(
        "keywords_in_context"
    ).raw


def test_seniority_alignment_reads_the_titles_actually_selected(example_profile):
    intern = JobDescription(raw="", title="Backend Engineer", seniority="intern")
    senior = JobDescription(raw="", title="Backend Engineer", seniority="senior")
    index = example_profile.sources()
    assert score(_doc(), example_profile, intern, index).component("title_fit").raw > score(
        _doc(), example_profile, senior, index
    ).component("title_fit").raw


def test_addresses_matches_a_technical_qualification_by_its_technologies():
    assert addresses("Strong PostgreSQL and Python", "Built it in Python on PostgreSQL")
    assert not addresses("Kubernetes and Terraform in production", "Built it in Python")


def test_addresses_matches_a_prose_qualification_by_vocabulary():
    assert addresses(
        "Comfortable owning a service end to end",
        "Owned the ingestion service end to end, including its on-call rotation",
    )
    assert not addresses("Comfortable presenting to executive stakeholders", "Wrote a parser")


def test_format_component_folds_in_the_parse_result(example_profile):
    failed = VerifyReport(ok=False, page_count=2, missing=["length: 2 pages, budget is 1"],
                          checks={"page_budget": False})
    passed = VerifyReport(ok=True, page_count=1, checks={"page_budget": True})
    index = example_profile.sources()
    assert score(_doc(), example_profile, POSTING, index, failed).component("format").raw < score(
        _doc(), example_profile, POSTING, index, passed
    ).component("format").raw


def test_an_overlong_bullet_fails_a_format_check(example_profile):
    long_doc = _doc(
        experience=[
            SelectedEntry(
                source_id="exp-northwind-backend",
                bullets=[Bullet(text="x " * 200, source_ids=["exp-northwind-backend.h1"])],
            )
        ]
    )
    detail = score(long_doc, example_profile, POSTING, example_profile.sources()).component("format").detail
    assert "bullets fit two lines" in detail


def test_a_posting_with_nothing_to_measure_does_not_score_zero(example_profile):
    """An empty requirement list means "nothing to cover", not "covered nothing"."""
    bare = JobDescription(raw="just vibes")
    result = score(_doc(), example_profile, bare, example_profile.sources())
    assert result.component("hard_skills").raw == 1.0
    assert result.component("qualifications").raw == 1.0


# ------------------------------------------------------------- feedback ----


def test_feedback_pushes_only_on_gaps_a_rewrite_can_close(example_profile):
    """Naming the unreachable ones would be an invitation to invent them, and ground.py
    would reject the result — costing an iteration to learn nothing."""
    jd = JobDescription(raw="", hard_skills=["Kubernetes", "SQLite"], keywords=["Kubernetes", "SQLite"])
    result = score(_doc(), example_profile, jd, example_profile.sources())
    text = feedback(result, 80.0)

    assert "WITHOUT adding anything the catalogue does not contain" in text
    assert "SQLite" in text.split("LEAVE THEM OUT")[0]
    assert "Kubernetes" in text.split("LEAVE THEM OUT")[1]


def test_feedback_reports_a_failed_parse_check(example_profile):
    report = VerifyReport(ok=False, page_count=2, missing=["length: 2 pages, budget is 1"])
    result = score(_doc(), example_profile, POSTING, example_profile.sources(), report)
    assert "2 pages, budget is 1" in feedback(result, 80.0, report)
