"""What a run cost.

The loop is the expensive part of this tool and it was the invisible part: "Iterations: 3"
is not a price, and the stopping rules are a trade nobody could see the cost of.

Two things are asserted here. That the count is right, including the retries that a naive
count would hide — and that metering can never take a run down, because it is bookkeeping
and a provider that omits a usage field must not be able to fail a résumé.
"""

import pytest

from resume_fill.config import Settings
from resume_fill.llm import LLMError, complete_json
from resume_fill.meter import Meter


class _Usage:
    def __init__(self, prompt: int, completion: int) -> None:
        self.prompt_tokens = prompt
        self.completion_tokens = completion


class _Response:
    def __init__(self, content: str, usage=None) -> None:
        self.choices = [type("C", (), {"message": type("M", (), {"content": content})()})()]
        self.usage = usage


class _Client:
    """Enough of the OpenAI client for complete_json, scripted per call."""

    def __init__(self, *responses) -> None:
        self._responses = list(responses)
        self.calls = 0
        self.chat = type("Chat", (), {"completions": self})()

    def create(self, **kwargs):
        self.calls += 1
        item = self._responses[min(self.calls - 1, len(self._responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return item


CFG = Settings(LLM_API_KEY="k", LLM_BASE_URL="https://example.invalid", LLM_MODEL="m")


@pytest.fixture
def patched(monkeypatch):
    def install(client):
        monkeypatch.setattr("resume_fill.llm._client", lambda cfg: client)
        return client

    return install


def test_one_call_is_counted_with_its_tokens(patched, monkeypatch):
    patched(_Client(_Response('{"ok": true}', _Usage(1200, 340))))
    meter = Meter()

    assert complete_json("s", "u", cfg=CFG, meter=meter) == {"ok": True}
    assert meter.calls == 1
    assert meter.prompt_tokens == 1200
    assert meter.completion_tokens == 340
    assert meter.total_tokens == 1540


def test_a_retry_is_counted_too(patched):
    """A round trip that came back as unparseable JSON cost the same wall clock and the same
    tokens as one that did not. A count that hid it would understate every run that had any."""
    client = _Client(_Response("not json at all", _Usage(900, 20)), _Response('{"ok": 1}', _Usage(900, 300)))
    patched(client)
    meter = Meter()

    complete_json("s", "u", cfg=CFG, meter=meter, retries=1)
    assert client.calls == 2
    assert meter.calls == 2
    assert meter.total_tokens == 2120


def test_a_failed_call_is_still_a_call(patched):
    patched(_Client(RuntimeError("connection reset")))
    meter = Meter()

    with pytest.raises(LLMError):
        complete_json("s", "u", cfg=CFG, meter=meter, retries=0)
    assert meter.calls == 1


def test_an_endpoint_that_reports_no_usage_does_not_break_anything(patched):
    """Not every OpenAI-compatible endpoint returns usage. A missing count is zero, never a
    crash: metering is bookkeeping and must not be able to fail a run."""
    patched(_Client(_Response('{"ok": 1}', usage=None)))
    meter = Meter()

    assert complete_json("s", "u", cfg=CFG, meter=meter) == {"ok": 1}
    assert meter.calls == 1
    assert meter.total_tokens == 0


def test_metering_is_optional(patched):
    patched(_Client(_Response('{"ok": 1}', _Usage(10, 10))))
    assert complete_json("s", "u", cfg=CFG) == {"ok": 1}


def test_the_summary_reads_as_a_sentence():
    meter = Meter()
    assert meter.summary() == "no model calls"

    meter.record(prompt=1000, completion=500, seconds=12.4)
    meter.record(prompt=1200, completion=600, seconds=9.1)
    summary = meter.summary()

    assert "2 model calls" in summary
    assert "3,300 tokens" in summary
    assert meter.as_dict()["seconds"] == pytest.approx(21.5)


def test_the_record_carries_it(example_profile, tmp_path, monkeypatch):
    """report.md is prose for a person; run.json is the same fact for anything that is not."""
    from test_pipeline import HONEST, POSTING

    from resume_fill import runrecord
    from resume_fill.pipeline import run

    meter = Meter()
    meter.record(prompt=2000, completion=800, seconds=30.0)
    out = tmp_path / "run"
    run(
        example_profile, POSTING, None,
        Settings(OUT_DIR=tmp_path / "out", MAX_ITER=1, SCORE_THRESHOLD=1),
        lambda s, u: HONEST, out_dir=out, mode="resume", meter=meter,
    )

    usage = runrecord.load(out).usage
    assert usage["calls"] == 1
    assert usage["total_tokens"] == 2800
    assert "Cost: 1 model call" in (out / "report.md").read_text(encoding="utf-8")
