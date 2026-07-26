from resume_fill.textutil import (
    contains_term,
    normalize,
    numbers,
    squash,
    supports_number,
    truncate,
)


def test_normalize_unifies_the_punctuation_a_paste_brings_with_it():
    assert normalize("“Senior”  Engineer – Data") == '"senior" engineer - data'


def test_contains_term_respects_word_boundaries():
    """A substring search for "R" or "Go" matches half the English language, and getting
    this wrong inflates the coverage score with skills nobody claimed."""
    assert contains_term("Wrote R scripts for the study", "R")
    assert not contains_term("Rewrote the reporting layer", "R")
    assert contains_term("Shipped a Go service", "Go")
    assert not contains_term("Ongoing migration work", "Go")


def test_contains_term_handles_punctuated_technology_names():
    assert contains_term("Ten years of C++ and C#", "C++")
    assert contains_term("Ten years of C++ and C#", "C#")
    assert not contains_term("Wrote C code", "C++")


def test_contains_term_tolerates_separator_variants():
    assert contains_term("Built the API in nodejs", "Node.js")
    assert contains_term("Built the API in Node JS", "Node.js")
    assert contains_term("Owns CICD", "CI/CD")


def test_contains_term_does_not_match_a_dotted_name_inside_a_word():
    """".NET" squashed is "net", which appears inside "Kubernetes". Matching on the squashed
    form would silently license a claim about a framework nobody named."""
    assert not contains_term("Ran the workers on Kubernetes.", ".NET")
    assert contains_term("Ported the service to ASP.NET", "ASP.NET")


def test_squash_is_still_available_for_identity_comparisons():
    assert squash("Node.js") == squash("nodejs") == "nodejs"
    assert not contains_term("Runs on MongoDB", "Go")


def test_numbers_finds_quantities_and_ignores_product_names():
    assert numbers("Cut latency 40% and served 12,000 users") == ["40%", "12000"]
    # S3 and EC2 are claims about tooling, checked as terms; treating the 3 as a quantity
    # would demand the source contain the number 3.
    assert numbers("Deployed to S3 and EC2 with Python3") == []


def test_supports_number_requires_the_figure_but_not_the_unit():
    source = "p95 dropped from 500ms to 300ms, about 40 percent"
    assert supports_number(source, "40%")
    assert not supports_number(source, "60%")


def test_supports_number_ignores_thousands_separators_and_trailing_zeros():
    assert supports_number("served 12000 requests", "12,000")
    assert supports_number("the factor was 3.0", "3x")


def test_truncate_marks_that_it_cut():
    assert truncate("abc", 5) == "abc"
    assert truncate("abcdefghij", 5) == "abcd…"  # no word boundary to use


def test_truncate_prefers_a_word_boundary():
    """These end up as citation labels in report.md, where "...single-threaded cro" reads
    as a bug rather than as a truncation."""
    assert truncate("Rewrote the single-threaded cron script", 32) == "Rewrote the single-threaded…"
