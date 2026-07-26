"""One OpenAI-compatible chat client, used by every stage that needs a model.

Everything downstream asks for JSON and gets a dict back. Stages take the call as a
parameter (`llm_call=`) rather than importing it directly, so tests drive the whole
pipeline with a stub and no network.
"""

import json
import re
import time
from collections.abc import Callable
from typing import Any

from .config import Settings
from .config import settings as default_settings

# A callable with complete_json's shape. Every stage that needs a model takes one of these.
LLMCall = Callable[..., dict[str, Any]]

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


class LLMError(RuntimeError):
    """Raised when the model is unreachable, unconfigured, or will not return JSON."""


class LLMNotConfigured(LLMError):
    def __init__(self) -> None:
        super().__init__(
            "No LLM configured. Copy .env.example to .env and set LLM_API_KEY, "
            "LLM_BASE_URL and LLM_MODEL (Cerebras and DeepSeek are both OpenAI-compatible)."
        )


def _client(cfg: Settings):
    from openai import OpenAI

    return OpenAI(api_key=cfg.LLM_API_KEY, base_url=cfg.LLM_BASE_URL, timeout=cfg.LLM_TIMEOUT_SEC)


def extract_json(raw: str) -> dict[str, Any]:
    """Parse a model response that is *supposed* to be a JSON object.

    Providers differ on how faithfully they honour response_format: some wrap the object
    in a markdown fence, some prepend a sentence. Strip the fence, then fall back to the
    outermost brace pair, before giving up.
    """
    text = _FENCE.sub("", raw or "").strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise LLMError(f"model did not return JSON: {raw[:400]!r}") from None
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise LLMError(f"model returned malformed JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise LLMError(f"expected a JSON object, got {type(parsed).__name__}")
    return parsed


def complete_json(
    system: str,
    user: str,
    *,
    cfg: Settings | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    retries: int = 2,
) -> dict[str, Any]:
    """Single round-trip to the model, JSON in / JSON out.

    Retries only transport and JSON-shape failures. A model that answers coherently but
    ungroundedly is not this function's problem — ground.py catches that.
    """
    cfg = cfg or default_settings
    if not cfg.llm_configured:
        raise LLMNotConfigured
    client = _client(cfg)
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = client.chat.completions.create(
                model=cfg.LLM_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={"type": "json_object"},
                max_tokens=max_tokens or cfg.LLM_MAX_TOKENS,
                temperature=cfg.LLM_TEMPERATURE if temperature is None else temperature,
            )
            return extract_json(resp.choices[0].message.content or "")
        except LLMError as exc:
            last = exc
        except Exception as exc:  # transport, rate limit, provider 5xx
            last = LLMError(f"{type(exc).__name__}: {exc}")
        if attempt < retries:
            time.sleep(1.5 * (attempt + 1))
    raise last if isinstance(last, LLMError) else LLMError(str(last))
