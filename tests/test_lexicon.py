from resume_fill.lexicon import canonical, find_terms, technical_tokens


def test_canonical_folds_the_variants_a_posting_and_a_resume_spell_differently():
    """Without this, "Postgres" on your résumé reads as a gap against "PostgreSQL" in the
    posting — a missing keyword that is not actually missing."""
    assert canonical("postgres") == "PostgreSQL"
    assert canonical("Golang") == "Go"
    assert canonical("k8s") == "Kubernetes"
    assert canonical("python") == "Python"
    assert canonical("Underwater Basket Weaving") == "Underwater Basket Weaving"


def test_find_terms_prefers_the_longest_match():
    assert "Spring Boot" in find_terms("Experience with Spring Boot required")


def test_find_terms_does_not_match_inside_words():
    assert find_terms("Ongoing rewrite of the reporting layer") == []


def test_find_terms_is_deduplicated_and_canonical():
    found = find_terms("Postgres, PostgreSQL and postgres again, plus Python")
    assert found.count("PostgreSQL") == 1
    assert "Python" in found


def test_technical_tokens_catches_tools_the_lexicon_never_heard_of():
    """The gate cannot only know curated names, or a bullet smuggles in any claim by
    naming an obscure product."""
    tokens = technical_tokens("Deployed with Kubermatic onto H100 nodes using FooBarDB")
    assert "H100" in tokens
    assert "FooBarDB" in tokens


def test_technical_tokens_leaves_prose_alone():
    """False positives are worse than misses here: every one becomes a violation the loop
    has to spend an iteration on."""
    tokens = technical_tokens(
        "Led a team of engineers in New York, NY to improve onboarding for the US market"
    )
    assert tokens == []


def test_technical_tokens_includes_curated_terms():
    assert "Kafka" in technical_tokens("Streamed events through Kafka")
