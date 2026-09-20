"""Progress is reported on a time basis and per cause, never per record."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

import pytest

from lawgraph.core import logging as lg
from lawgraph.core.progress import PeriodicLog, Progress
from lawgraph.pipelines.retrieve.base import RetrievePipelineBase, RetrieveRecord
from tests.fakes import RawSourcesFake


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_the_line_has_position_total_rate_eta_and_counters() -> None:
    clock = _Clock()
    progress = Progress("judgments", total=34_593, clock=clock)
    progress.ok(12_397)
    progress.skip("no content (HTTP 404)", count=3)
    clock.now += 2530  # 12,400 handled in 2,530 s = 4.9/s

    assert progress.line() == (
        "12,400 / 34,593 (36%) judgments · 4.9/s · ~1h15m left · 3 skipped · 0 errors"
    )


def test_without_a_total_there_is_no_share_and_no_eta() -> None:
    clock = _Clock()
    progress = Progress(clock=clock)
    progress.ok(50)
    clock.now += 10
    assert progress.line() == "50 records · 5.0/s · 0 skipped · 0 errors"


def test_ten_thousand_records_log_a_line_a_minute_not_a_line_a_record(
    caplog: pytest.LogCaptureFixture,
) -> None:
    clock = _Clock()
    progress = Progress(total=10_000, clock=clock)
    with caplog.at_level(logging.INFO):
        for number in range(10_000):
            clock.now += 0.2  # 5 records a second: 2,000 s
            if number % 10 == 0:
                progress.skip("no content (HTTP 404)", f"doc-{number}")
            elif number % 1000 == 1:
                progress.fail("download failed (HTTP 500)", f"doc-{number}")
            else:
                progress.ok()
        progress.finish()

    info = [r for r in caplog.records if r.levelno == logging.INFO]
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(info) < 50  # 33 status lines, one first skip, one summary
    assert len(warnings) == 1  # one per cause, not one per failed record
    assert "first: doc-1" in warnings[0].getMessage()
    summary = info[-1].getMessage()
    assert "8,990 records done" in summary
    assert "1,000 skipped (no content (HTTP 404): 1,000)" in summary
    assert "10 failed (download failed (HTTP 500): 10)" in summary
    assert "in 33m20s" in summary


def test_periodic_log_is_due_once_per_interval() -> None:
    clock = _Clock()
    periodic = PeriodicLog(60, clock=clock)
    assert not periodic.due()
    clock.now += 61
    assert periodic.due() and not periodic.due()
    assert PeriodicLog(60, immediate=True, clock=clock).due()


# ── through a retrieve pipeline ──────────────────────────────────────────────


class _Store(RawSourcesFake):
    def insert_raw_source(self, **_kw: Any) -> None:
        pass


class _Pipeline(RetrievePipelineBase):
    def fetch(self, **kwargs: Any) -> Iterator[RetrieveRecord]:  # type: ignore[override]
        self.progress.expect(10_000)
        for number in range(10_000):
            if number % 4 == 0:
                self.progress.skip("no XML (HTTP 404)", number)
                continue
            yield RetrieveRecord("test", "kind", str(number), payload_json={})


def test_a_retrieve_of_ten_thousand_records_logs_a_handful_of_lines(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO):
        result = _Pipeline(_Store()).run()  # type: ignore[arg-type]

    assert (result.created, result.skipped, result.errors) == (7_500, 2_500, [])
    assert len([r for r in caplog.records if r.levelno >= logging.INFO]) < 50


def test_a_cause_of_failure_is_one_error_of_the_result() -> None:
    class Failing(_Store):
        def insert_raw_source(self, **_kw: Any) -> None:
            raise RuntimeError("write failed")

    records = (
        RetrieveRecord("test", "kind", str(n), payload_json={}) for n in range(30)
    )

    class P(RetrievePipelineBase):
        def fetch(self, **kwargs: Any) -> Iterator[RetrieveRecord]:  # type: ignore[override]
            return records

    result = P(Failing()).run()  # type: ignore[arg-type]
    assert result.created == 0 and result.skipped == 30
    assert result.errors == [
        "30 x could not be stored (first: test/kind/0: write failed)"
    ]


# ── step context and JSON mode ───────────────────────────────────────────────


def _format(formatter: logging.Formatter, message: str) -> str:
    record = logging.LogRecord(
        "lawgraph.core.progress", logging.INFO, __file__, 1, message, None, None
    )
    lg._StepFilter().filter(record)
    return formatter.format(record)


def test_the_status_line_carries_the_step_in_plain_and_json_mode() -> None:
    clock = _Clock()
    progress = Progress("judgments", total=100, clock=clock)
    progress.ok(40)
    clock.now += 10
    line = progress.line()

    with lg.log_step("retrieve rechtspraak"):
        plain = _format(logging.Formatter(lg.LOG_FORMAT), line)
        entry = json.loads(_format(lg._JsonFormatter(), line))

    assert "[retrieve rechtspraak] core.progress: 40 / 100 (40%) judgments" in plain
    assert entry["step"] == "retrieve rechtspraak"
    assert entry["message"].startswith("40 / 100 (40%) judgments · 4.0/s")
