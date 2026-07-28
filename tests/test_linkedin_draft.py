"""Proposed LinkedIn copy: grounded like everything else, and printed rather than posted."""

import pytest

from resume_fill.config import Settings
from resume_fill.document import LinkedInDraft
from resume_fill.ground import check_linkedin
from resume_fill.linkedin_draft import build_prompt, current_copy, render, write

CFG = Settings()

DRAFT = {
    "headline": {
        "text": "Backend engineer — data pipelines in Python and PostgreSQL",
        "source_ids": ["skills"],
    },
    "about": [
        {
            "text": "I like the unglamorous part of data work: the nightly job that has to finish "
            "before anyone wakes up. At Northwind I rewrote one from a single-threaded cron "
            "script to an asyncio worker pool and took it from 51 minutes to 9.",
            "source_ids": ["exp-northwind-backend.h1"],
        },
        {
            "text": "I also put contract tests around the 14 upstream feeds, which caught 3 silent "
            "schema changes in the first month.",
            "source_ids": ["exp-northwind-backend.h2"],
        },
    ],
    "experience": [
        {
            "source_id": "exp-northwind-backend",
            "paragraphs": [
                {
                    "text": "Owned the ingestion path end to end for a six-person data team.",
                    "source_ids": ["exp-northwind-backend"],
                }
            ],
        }
    ],
}


def _draft(**kwargs) -> LinkedInDraft:
    return LinkedInDraft.model_validate({**DRAFT, **kwargs})


# ---------------------------------------------------------------- gate ----


def test_a_grounded_draft_passes(example_profile):
    assert check_linkedin(_draft(), example_profile, example_profile.sources()) == []


def test_the_headline_is_checked_like_everything_else(example_profile):
    """A LinkedIn profile is the most-read thing you write and the least reviewed."""
    draft = _draft(headline={"text": "Kubernetes and Terraform specialist", "source_ids": ["skills"]})
    violations = check_linkedin(draft, example_profile, example_profile.sources())
    assert [v.kind for v in violations] == ["unsupported_term", "unsupported_term"]
    assert {"Kubernetes", "Terraform"} == {v.detail.split('"')[1] for v in violations}


def test_an_uncited_about_paragraph_is_blocked(example_profile):
    draft = _draft(about=[{"text": "I am a highly motivated self-starter.", "source_ids": []}])
    kinds = [v.kind for v in check_linkedin(draft, example_profile, example_profile.sources())]
    assert kinds == ["uncited_bullet"]


def test_copy_for_a_role_that_does_not_exist_is_blocked(example_profile):
    draft = _draft(experience=[{"source_id": "exp-google-l7", "paragraphs": []}])
    kinds = [v.kind for v in check_linkedin(draft, example_profile, example_profile.sources())]
    assert kinds == ["unknown_entry"]


# ------------------------------------------------------- current copy ----


def test_current_copy_prefers_the_export_over_the_record(example_profile, linkedin_export):
    """profile.yaml is only approximately what LinkedIn says: `init` merges résumé bullets
    over the export's descriptions, so diffing against the record hides exactly the change
    you want to make."""
    from_export = current_copy(example_profile, linkedin_export)
    assert from_export.headline == "Backend engineer"

    from_record = current_copy(example_profile, None)
    assert from_record.headline == example_profile.basics.headline
    assert from_record.headline != from_export.headline


def test_current_copy_falls_back_to_the_record_when_there_is_no_export(example_profile, tmp_path):
    current = current_copy(example_profile, tmp_path / "nope")
    assert current.experience["exp-northwind-backend"]


# -------------------------------------------------------------- prompt ----


def test_the_prompt_forbids_the_thing_linkedin_copy_always_does(example_profile):
    system, user = build_prompt(example_profile, None, current_copy(example_profile), CFG)
    assert "It is not allowed to be vaguer" in system
    assert "no emoji" in user
    assert "CURRENT PROFILE COPY" in user


def test_write_retries_with_the_rejection_reason(example_profile):
    prompts = []
    bad = {**DRAFT, "headline": {"text": "Kubernetes specialist", "source_ids": ["skills"]}}

    def call(system, user):
        prompts.append(user)
        return bad if len(prompts) == 1 else DRAFT

    result = write(example_profile, None, CFG, call)
    assert result.ok
    assert result.attempts == 2
    assert "Kubernetes" in prompts[1]
    assert "WHY THE LAST ATTEMPT WAS REJECTED" in prompts[1]


def test_write_reports_a_draft_it_could_never_ground(example_profile):
    bad = {**DRAFT, "headline": {"text": "Kubernetes specialist", "source_ids": ["skills"]}}
    result = write(example_profile, None, Settings(MAX_ITER=2), lambda s, u: bad)
    assert not result.ok
    assert result.violations


def test_write_rejects_copy_of_the_wrong_shape(example_profile):
    from resume_fill.llm import LLMError

    with pytest.raises(LLMError, match="does not fit the schema"):
        write(example_profile, None, CFG, lambda s, u: {"about": "one long string"})


# -------------------------------------------------------------- render ----


def test_render_shows_the_copy_and_the_diff(example_profile):
    result = write(example_profile, None, CFG, lambda s, u: DRAFT)
    body = render(result, example_profile)

    assert "## Headline" in body and "## About" in body
    assert "Backend engineer — data pipelines in Python and PostgreSQL" in body
    assert "```diff" in body
    assert "+I like the unglamorous part" in body or "+I like the unglamorous" in body
    # The citation trail survives into the pasteable output.
    assert "- **headline**" in body
    assert "source:" in body


def test_render_says_why_this_is_paste_and_not_post(example_profile):
    """PLAN.md decision 1 is the finding, not a workaround, and the output says so."""
    result = write(example_profile, None, CFG, lambda s, u: DRAFT)
    body = render(result, example_profile)
    assert "no public write API" in body
    assert "User Agreement §8.2" in body


def test_render_warns_loudly_when_the_draft_was_rejected(example_profile):
    bad = {**DRAFT, "headline": {"text": "Kubernetes specialist", "source_ids": ["skills"]}}
    result = write(example_profile, None, Settings(MAX_ITER=1), lambda s, u: bad)
    body = render(result, example_profile)
    assert "Do not" in body and "paste it as-is" in body
    assert "unsupported_term" in body


def test_the_diff_wraps_before_comparing(example_profile):
    """LinkedIn copy is a handful of very long lines; diffing those whole reports every
    paragraph as entirely changed and tells you nothing."""
    result = write(example_profile, None, CFG, lambda s, u: DRAFT)
    body = render(result, example_profile)

    diff_lines, inside = [], False
    for line in body.splitlines():
        if line.startswith("```diff"):
            inside = True
        elif line.startswith("```"):
            inside = False
        elif inside and line.startswith(("+", "-")):
            diff_lines.append(line)

    assert diff_lines
    assert max(len(ln) for ln in diff_lines) < 100


def test_a_module_that_never_touches_linkedin():
    """The strongest form of the guarantee: there is no client, no session, no URL."""
    from pathlib import Path

    source = Path("resume_fill/linkedin_draft.py").read_text(encoding="utf-8")
    body = source.split('"""', 2)[-1]  # the module docstring explains why; the code must not
    assert "linkedin.com" not in body
    assert "httpx" not in body
    assert "requests" not in body
