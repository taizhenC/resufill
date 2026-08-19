"""One run at a time, in a worker thread.

Deliberately stdlib-only and in-memory. A queue or a broker would be absurd for a
single-user local app, and the durable record of a run is the directory it writes — this
is only the live view `/api/runs/current` serves while it is happening.

A thread rather than an async task, for a concrete reason: `render.py` uses Playwright's
**sync** API, which raises if it finds a running asyncio event loop. A plain
`threading.Thread` has none, so the pipeline runs there unmodified. That is also why the
lock is a `threading.Lock` and not an `asyncio.Lock`.
"""

from __future__ import annotations

import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field

MAX_EVENTS = 400


def now_ms() -> int:
    return int(time.time() * 1000)


class Busy(RuntimeError):
    """A run is already in progress. The API turns this into a 409."""


@dataclass
class JobState:
    id: int
    mode: str
    started_at_ms: int
    run_id: str = ""
    out_dir: str = ""
    stage: str = "starting"
    detail: dict = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)
    cancel_event: threading.Event = field(default_factory=threading.Event)
    done: bool = False
    cancelled: bool = False
    ok: bool = False
    error: str | None = None
    finished_at_ms: int | None = None
    # What the run has cost so far. The browser shows it live, which is the only place the
    # price of another iteration is visible while there is still time to cancel one.
    usage: dict = field(default_factory=dict)
    # The worker writes and the request thread reads; both go through this.
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def report(self, stage: str, detail: dict) -> None:
        """The Progress sink. Keeps the whole stage log, not just the latest, because the
        browser polls at ~1s and stages can be closer together than that — a poller that
        only ever sees `stage` would silently miss the ones in between."""
        with self._lock:
            self.stage = stage
            self.detail = dict(detail)
            self.events.append({"stage": stage, "at_ms": now_ms(), **detail})
            if len(self.events) > MAX_EVENTS:
                del self.events[: len(self.events) - MAX_EVENTS]

    def set(self, **fields) -> None:
        with self._lock:
            for key, value in fields.items():
                setattr(self, key, value)

    def snapshot(self, *, since: int = 0) -> dict:
        """`since` is an index into the event log, so the client can ask only for what it
        has not seen and the response stays small on a long run."""
        with self._lock:
            return {
                "id": self.id,
                "mode": self.mode,
                "run_id": self.run_id,
                "stage": self.stage,
                "detail": dict(self.detail),
                "events": self.events[max(0, since) :],
                "event_count": len(self.events),
                "started_at_ms": self.started_at_ms,
                "finished_at_ms": self.finished_at_ms,
                "cancel_requested": self.cancel_event.is_set(),
                "cancelled": self.cancelled,
                "done": self.done,
                "ok": self.ok,
                "error": self.error,
                "usage": dict(self.usage),
            }


class JobRunner:
    """Owns the lock. Every way of starting a run goes through here, so there is one place
    that decides whether the machine is busy."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._job: JobState | None = None
        self._seq = 0

    @property
    def current(self) -> JobState | None:
        return self._job

    @property
    def busy(self) -> bool:
        return self._job is not None and not self._job.done

    def start(self, work: Callable[[JobState], None], *, mode: str) -> JobState:
        """Spawn the worker, or raise Busy. Non-blocking acquire: a caller asking to start
        a second run wants to be told no, not to wait behind the first one."""
        if not self._lock.acquire(blocking=False):
            raise Busy("a run is already in progress")
        self._seq += 1
        state = JobState(id=self._seq, mode=mode, started_at_ms=now_ms())
        self._job = state

        def worker() -> None:
            try:
                work(state)
            except Exception as exc:
                # Including Cancelled raised before any stage completed. The message is
                # what the UI shows, so it has to say something a person can act on.
                state.set(error=f"{type(exc).__name__}: {exc}")
                if not isinstance(exc, KeyboardInterrupt):
                    traceback.print_exc()
            finally:
                state.set(done=True, finished_at_ms=now_ms())
                self._lock.release()

        threading.Thread(target=worker, name=f"resume-fill-run-{state.id}", daemon=True).start()
        return state

    def cancel(self) -> bool:
        """Request a stop. Cooperative: the pipeline notices at its next stage boundary."""
        job = self._job
        if job is None or job.done:
            return False
        job.cancel_event.set()
        return True

    def wait(self, timeout: float = 60.0) -> bool:
        """Block until the current run finishes. Tests use this; nothing in the server does."""
        deadline = time.time() + timeout
        while self.busy and time.time() < deadline:
            time.sleep(0.02)
        return not self.busy
