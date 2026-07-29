import threading

import pytest

from resume_fill.jobs import Busy, JobRunner, JobState


def test_one_run_at_a_time():
    """Non-blocking acquire on purpose: a caller asking to start a second run wants to be
    told no, not to wait behind the first one."""
    runner = JobRunner()
    release = threading.Event()
    runner.start(lambda state: release.wait(5), mode="both")

    assert runner.busy
    with pytest.raises(Busy):
        runner.start(lambda state: None, mode="both")

    release.set()
    assert runner.wait()
    assert not runner.busy


def test_the_lock_is_released_even_when_the_work_raises():
    """Otherwise one failed run wedges the server until it is restarted."""
    runner = JobRunner()

    def explode(state):
        raise ValueError("boom")

    state = runner.start(explode, mode="resume")
    assert runner.wait()
    assert state.done and "boom" in state.error
    runner.start(lambda s: None, mode="resume")  # not wedged
    assert runner.wait()


def test_events_accumulate_so_a_one_second_poller_misses_nothing():
    """Stages can land closer together than the poll interval. A client that only ever
    read `stage` would silently skip the ones in between."""
    runner = JobRunner()

    def work(state: JobState) -> None:
        state.report("tailoring", {"attempt": 1})
        state.report("grounding", {"attempt": 1})
        state.report("scored", {"attempt": 1, "score": 71.2})

    state = runner.start(work, mode="resume")
    assert runner.wait()

    snapshot = state.snapshot()
    assert [e["stage"] for e in snapshot["events"]] == ["tailoring", "grounding", "scored"]
    assert snapshot["stage"] == "scored"
    assert snapshot["detail"]["score"] == 71.2
    assert all("at_ms" in e for e in snapshot["events"])


def test_since_returns_only_what_the_client_has_not_seen():
    runner = JobRunner()

    def work(state: JobState) -> None:
        for i in range(5):
            state.report("tailoring", {"attempt": i})

    state = runner.start(work, mode="resume")
    assert runner.wait()
    assert state.snapshot()["event_count"] == 5
    assert len(state.snapshot(since=3)["events"]) == 2
    assert state.snapshot(since=99)["events"] == []


def test_cancel_sets_the_flag_the_pipeline_watches():
    runner = JobRunner()
    seen = threading.Event()
    finish = threading.Event()

    def work(state: JobState) -> None:
        seen.set()
        finish.wait(5)

    state = runner.start(work, mode="resume")
    seen.wait(5)
    assert runner.cancel() is True
    assert state.cancel_event.is_set()
    assert state.snapshot()["cancel_requested"] is True

    finish.set()
    assert runner.wait()
    assert runner.cancel() is False  # nothing in progress


def test_cancel_with_no_run_is_not_an_error():
    assert JobRunner().cancel() is False


def test_playwright_sync_api_works_inside_the_worker_thread():
    """The assumption the whole design rests on.

    render.py uses Playwright's *sync* API, which raises if it finds a running asyncio
    event loop. A thread has none — which is why the runner spawns a thread rather than an
    async task, and why the lock is a threading.Lock. If this ever stops being true, every
    run through the server breaks and nothing else would say why.
    """
    from conftest import chromium_available

    if not chromium_available():
        pytest.skip("needs `playwright install chromium`")

    runner = JobRunner()
    result = {}

    def work(state: JobState) -> None:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            result["ok"] = True
            browser.close()

    state = runner.start(work, mode="resume")
    assert runner.wait(120)
    assert state.error is None
    assert result.get("ok") is True


def test_the_event_log_is_bounded():
    """A pathological run must not grow the snapshot without limit."""
    from resume_fill.jobs import MAX_EVENTS

    state = JobState(id=1, mode="resume", started_at_ms=0)
    for i in range(MAX_EVENTS + 50):
        state.report("tailoring", {"n": i})
    assert state.snapshot()["event_count"] == MAX_EVENTS
    assert state.snapshot()["events"][-1]["n"] == MAX_EVENTS + 49
