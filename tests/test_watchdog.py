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
