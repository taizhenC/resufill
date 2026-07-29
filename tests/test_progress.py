import threading

import pytest

from resume_fill.progress import Cancelled, Progress, printer


def test_the_default_progress_is_a_no_op():
    """Every stage in the pipeline calls it unconditionally, so no caller is obliged to
    care and the library stays usable without any of this."""
    report = Progress()
    report("tailoring", attempt=1)
    report.checkpoint()
    assert report.history == [("tailoring", {"attempt": 1})]
    assert not report.cancelled


def test_reports_reach_the_sink_with_their_detail():
    seen = []
    report = Progress(sink=lambda stage, detail: seen.append((stage, detail)))
    report("rendering", document="resume", attempt=2, attempts=4)
    assert seen == [("rendering", {"document": "resume", "attempt": 2, "attempts": 4})]


def test_history_is_kept_even_without_a_sink():
    """A caller that attaches late, or a cancelled run being written to disk, still has
    the trail."""
    report = Progress()
    report("tailoring")
    report("grounding")
    assert [stage for stage, _ in report.history] == ["tailoring", "grounding"]


def test_a_report_raises_once_cancellation_is_requested():
    """Reporting and cancelling happen at the same instants — the stage boundaries are the
    only points the pipeline is between two blocking calls."""
    event = threading.Event()
    report = Progress(cancel=event)
    report("tailoring")

    event.set()
    assert report.cancelled
    with pytest.raises(Cancelled):
        report("grounding")


def test_checkpoint_can_be_called_without_reporting():
    event = threading.Event()
    report = Progress(cancel=event)
    report.checkpoint()
    event.set()
    with pytest.raises(Cancelled):
        report.checkpoint()


def test_a_cancelled_report_is_not_recorded():
    """It never happened — the stage was refused, not performed."""
    event = threading.Event()
    seen = []
    report = Progress(sink=lambda s, d: seen.append(s), cancel=event)
    event.set()
    with pytest.raises(Cancelled):
        report("rendering")
    assert report.history == []
    assert seen == []


def test_printer_sink_writes_one_line_per_stage(capsys):
    emit = printer()
    emit("scored", {"attempt": 1, "score": 71.2, "empty": ""})
    line = capsys.readouterr().out
    assert "scored" in line and "attempt=1" in line and "score=71.2" in line
    assert "empty" not in line
