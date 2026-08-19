"""What a run cost, counted rather than guessed.

The loop is the expensive part of this tool and it was also the invisible part. "Iterations:
3" is in report.md, but an iteration is a tailor call plus a Chromium launch plus a PDF
parse, and none of those cost the same — so the one number that people actually care about,
*how much did asking this question cost me*, was not written down anywhere.

It matters more than it sounds, because the loop's stopping rules (pipeline._stop_reason)
are a trade between spending and quality. A trade nobody can see the price of is a trade
nobody can tune. With this, "stopped at the ceiling after 1 attempt" and "used its whole
budget of 4" are visibly different amounts of money rather than two lines that look alike.

Deliberately not a price in currency. Rates differ per provider, change without notice, and
a stale multiplier printed with two decimal places would be worse than no number at all.
Tokens and calls are facts; dollars would be a guess wearing a dollar sign.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass
class Meter:
    """Counts model calls across a run. Shared by every stage; safe across threads because
    the web UI runs the pipeline in one and reads the record from another."""

    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    # Wall clock spent *inside* model calls, which is most but not all of a run — the rest
    # is Chromium and pdfminer, and the difference is worth being able to see.
    seconds: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def record(self, *, prompt: int = 0, completion: int = 0, seconds: float = 0.0) -> None:
        with self._lock:
            self.calls += 1
            self.prompt_tokens += prompt
            self.completion_tokens += completion
            self.seconds += seconds

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def as_dict(self) -> dict[str, float | int]:
        return {
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "seconds": round(self.seconds, 1),
        }

    def summary(self) -> str:
        if not self.calls:
            return "no model calls"
        line = f"{self.calls} model call{'s' if self.calls != 1 else ''}"
        if self.total_tokens:
            line += f", {self.total_tokens:,} tokens"
        if self.seconds:
            line += f", {self.seconds:.0f}s waiting on the model"
        return line


class _Timer:
    """Times one call and records it, whatever the call does — a failed round trip cost the
    same wall clock as a successful one, and a provider that bills on it bills for both."""

    def __init__(self, meter: Meter | None) -> None:
        self.meter = meter
        self.started = 0.0
        self.prompt = 0
        self.completion = 0

    def __enter__(self) -> _Timer:
        self.started = time.monotonic()
        return self

    def __exit__(self, *exc_info) -> None:
        if self.meter is not None:
            self.meter.record(
                prompt=self.prompt,
                completion=self.completion,
                seconds=time.monotonic() - self.started,
            )


def timed(meter: Meter | None) -> _Timer:
    return _Timer(meter)
