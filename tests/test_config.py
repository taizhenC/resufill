from pathlib import Path

from resume_fill.config import PACKAGE_DIR, Settings


def test_llm_configured_needs_all_three_fields():
    assert not Settings(LLM_API_KEY="", LLM_BASE_URL="u", LLM_MODEL="m").llm_configured
    assert not Settings(LLM_API_KEY="k", LLM_BASE_URL="", LLM_MODEL="m").llm_configured
    assert not Settings(LLM_API_KEY="k", LLM_BASE_URL="u", LLM_MODEL="").llm_configured
    assert Settings(LLM_API_KEY="k", LLM_BASE_URL="u", LLM_MODEL="m").llm_configured


def test_template_dirs_prefer_user_override_then_packaged():
    cfg = Settings(TEMPLATES_DIR=Path("/somewhere/templates"))
    assert cfg.template_dirs == [Path("/somewhere/templates"), PACKAGE_DIR / "templates"]
