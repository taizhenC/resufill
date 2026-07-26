import pytest

from resume_fill.config import Settings
from resume_fill.llm import LLMError, LLMNotConfigured, complete_json, extract_json


def test_extract_json_plain():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_strips_markdown_fence():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_recovers_from_leading_prose():
    """Providers that ignore response_format often prepend a sentence. The object is
    still in there, and re-asking costs a round trip, so dig it out."""
    assert extract_json('Sure! Here is the JSON:\n{"a": [1, 2]}\nHope that helps.') == {"a": [1, 2]}


def test_extract_json_rejects_non_object():
    with pytest.raises(LLMError):
        extract_json("[1, 2, 3]")


def test_extract_json_rejects_garbage():
    with pytest.raises(LLMError):
        extract_json("no json here at all")


def test_complete_json_without_credentials_is_actionable():
    cfg = Settings(LLM_API_KEY="", LLM_BASE_URL="https://example.invalid", LLM_MODEL="m")
    with pytest.raises(LLMNotConfigured) as exc:
        complete_json("sys", "user", cfg=cfg)
    assert ".env" in str(exc.value)
