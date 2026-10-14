"""The watchdog names the steps that run and the long statements of the process."""

from __future__ import annotations

import pytest

from lawgraph.pipelines import watchdog


def test_the_report_names_the_running_steps_and_the_long_statements(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    asked: list[float] = []

    def activity(min_seconds: float) -> list[dict]:
        asked.append(min_seconds)
        return [
            {
                "pid": 4711,
                "state": "active",
                "seconds": 7380,
                "wait": "",
                "query": "FETCH FORWARD 1000 FROM lg_x",
            }
        ]

    monkeypatch.setattr(watchdog, "own_activity", activity)
    monkeypatch.setattr(watchdog, "_start", lambda: None)  # no thread in a test
    monkeypatch.setattr(watchdog, "_clock", lambda: 100.0)
    with (
        watchdog.watched("semantic all"),
        watchdog.watched("semantic tk-government"),
        caplog.at_level("INFO"),
    ):
        watchdog.report(now=100.0 + 7_500)
    assert caplog.messages == [
        "Still running: semantic all for 2h05m, semantic tk-government for 2h05m.",
        "Statement 4711 for 2h03m (active): FETCH FORWARD 1000 FROM lg_x",
    ]
    assert asked == [watchdog.LONG_STATEMENT_SECONDS]


def test_no_report_while_no_step_runs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(
        watchdog, "own_activity", lambda _s: pytest.fail("nothing to ask")
    )
    with caplog.at_level("INFO"):
        watchdog.report()
    assert caplog.messages == []


def test_a_report_that_fails_is_a_warning_the_first_time_and_never_ends_the_run(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def report() -> None:
        raise PermissionError("pg_stat_activity")

    monkeypatch.setattr(watchdog, "report", report)
    with caplog.at_level("DEBUG"):
        assert watchdog.report_safely(first_failure=True) is False
        assert watchdog.report_safely(first_failure=False) is False
    assert [(r.levelname, bool(r.exc_info)) for r in caplog.records] == [
        ("WARNING", True),
        ("DEBUG", True),
    ]


def test_a_report_that_works_says_so() -> None:
    assert watchdog.report_safely(first_failure=True) is True
