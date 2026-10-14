"""A part of the warm-up that fails is logged with its traceback, and the rest goes on."""

from __future__ import annotations

import pytest

from lawgraph.api import app, dependencies, warm
from lawgraph.db import version_cache


def _broken(*_args: object) -> None:
    raise KeyError("x")


def _failures(caplog: pytest.LogCaptureFixture) -> list[tuple[str, object]]:
    return [(r.levelname, r.exc_info and r.exc_info[0]) for r in caplog.records]


def test_a_part_that_fails_is_a_warning_with_its_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("WARNING"):
        assert warm._run("stats", _broken) is False
    assert _failures(caplog) == [("WARNING", KeyError)]
    assert caplog.messages == ["Warm-up of stats failed: KeyError: 'x'"]


def test_a_warmer_that_fails_is_a_warning_with_its_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("WARNING"):
        version_cache._quietly(_broken, object())
    assert _failures(caplog) == [("WARNING", KeyError)]


def test_the_api_starts_without_its_warm_up_and_says_why(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(app, "API_WARM_UP", True)
    monkeypatch.setattr(version_cache, "on_new_version", lambda _warm: None)
    monkeypatch.setattr(dependencies, "get_store", _broken)
    with caplog.at_level("WARNING"):
        app._start_warm_up()
    assert _failures(caplog) == [("WARNING", KeyError)]
