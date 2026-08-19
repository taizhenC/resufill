from resume_fill.lexicon import base_forms, canonical, equivalents, find_terms, technical_tokens


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


def test_technical_tokens_sees_through_a_possessive():
    """"DeepMind's platform" names DeepMind. Leaving the "'s" on makes the token fail the
    shape test and slip through unchecked."""
    assert "DeepMind" in technical_tokens("DeepMind's platform")


def test_technical_tokens_leaves_prose_alone():
    """False positives are worse than misses here: every one becomes a violation the loop
    has to spend an iteration on."""
    tokens = technical_tokens(
        "Led a team of engineers in New York, NY to improve onboarding for the US market"
    )
    assert tokens == []


def test_technical_tokens_includes_curated_terms():
    assert "Kafka" in technical_tokens("Streamed events through Kafka")


def test_equivalents_reads_both_directions():
    """The tailor is told to write in the posting's vocabulary. If the posting says CI/CD
    and the highlight says "continuous integration", both spellings have to license each
    other or rule 9 of the tailor prompt fights the gate."""
    assert "continuous integration" in equivalents("CI/CD")
    assert "CI/CD" in equivalents("continuous integration")


def test_equivalents_reaches_through_an_alias():
    """"Postgres" and "PostgreSQL" are one concept, and the group is keyed on the
    canonical name, so asking with either spelling finds the other."""
    assert "PostgreSQL" in equivalents("postgres")
    assert "postgres" in equivalents("PostgreSQL")


def test_equivalents_is_empty_for_an_ordinary_word():
    assert equivalents("throughput") == ()
    assert equivalents("") == ()


def test_cv_is_deliberately_not_expanded():
    """A résumé is also a CV. A gate that cannot tell "computer vision" from the document
    it is checking is not a gate — the empty entry in EXPANSIONS records that on purpose."""
    assert "computer vision" not in equivalents("CV")


def test_base_forms_strips_one_derivation_not_two():
    """"Dockerized" is a claim about Docker. "Dockeriz" is not a word anybody wrote down,
    which is what stripping "ed" as well would produce."""
    assert base_forms("Dockerized") == ("Docker",)
    assert base_forms("Terraforming") == ("Terraform",)


def test_base_forms_leaves_a_name_that_merely_ends_in_a_suffix_alone():
    assert base_forms("Kubernetes") == ()
    assert base_forms("Redis") == ()
