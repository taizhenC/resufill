"""Stage-level progress reporting and cooperative cancellation, in one object.

They belong together because they happen at the same instants. A run is a handful of LLM
round trips and Chromium launches: 10 to 60 seconds each, with nothing to say in between.
The stage boundaries are the only points where the pipeline is between two blocking calls,
which makes them simultaneously the only useful moments to *report* from and the only safe
moments to *stop* at. Splitting them into two mechanisms would mean threading two
parameters through the same call sites to be checked on the same lines.

On a terminal the silence is fine. In a browser it looks like the thing has crashed, which
is why this exists at all.

Cancellation is cooperative on purpose. Killing the thread mid-render would leave a
half-written PDF in `out/`, and there is no version of "stop faster" that is worth an
artefact nobody can tell is corrupt.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field

# What the pipeline emits. `detail` carries whatever the stage knows — the attempt number,
# the document being worked on, the score it just computed.
Sink = Callable[[str, dict], None]

# Stage names, as constants because the API serialises them and the UI switches on them.
PARSING_JD = "parsing_jd"
TAILORING = "tailoring"
GROUNDING = "grounding"
REPAIRED = "repaired"
REJECTED = "rejected"
RENDERING = "rendering"
VERIFYING = "verifying"
SCORING = "scoring"
SCORED = "scored"
WRITING_REPORT = "writing_report"
DONE = "done"
CANCELLED = "cancelled"

# Ordered, for anything that wants to show a run's shape before it happens.
STAGES = (
    PARSING_JD, TAILORING, GROUNDING, REPAIRED, REJECTED, RENDERING, VERIFYING, SCORING, SCORED,
    WRITING_REPORT, DONE, CANCELLED,
)


class Cancelled(RuntimeError):
    """Raised at a stage boundary when cancellation was requested."""


@dataclass
class Progress:
    """Call it to report a stage; it checks for cancellation on the way through.

    The default instance does nothing and never cancels, so every stage in the pipeline can
    call it unconditionally and no caller is obliged to care.
    """

    sink: Sink | None = None
    cancel: threading.Event | None = None
    # Everything reported so far, in order. Kept so a caller that attaches late — or a
    # cancelled run being written to disk — still has the trail.
    history: list[tuple[str, dict]] = field(default_factory=list)

    def __call__(self, stage: str, **detail) -> None:
        self.checkpoint()
        self.history.append((stage, detail))
        if self.sink is not None:
            self.sink(stage, detail)

    def checkpoint(self) -> None:
        """Stop here if cancellation was requested. Called by every report, so the stage
        boundaries are the cancellation points without anyone writing them twice."""
        if self.cancel is not None and self.cancel.is_set():
            raise Cancelled("run cancelled")

    @property
    def cancelled(self) -> bool:
        return self.cancel is not None and self.cancel.is_set()


def printer(prefix: str = "  ") -> Sink:
    """A sink that writes each stage to stdout — what the CLI uses for --verbose."""

    def emit(stage: str, detail: dict) -> None:
        bits = " ".join(f"{k}={v}" for k, v in detail.items() if v not in (None, "", []))
        print(f"{prefix}{stage}{(' ' + bits) if bits else ''}", flush=True)

    return emit
