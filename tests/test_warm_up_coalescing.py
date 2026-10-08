"""The warm-up of the API under a run of the pipelines, which raises the data version with
every statement that writes: at most one waits (the newest data), it starts once the version
stands still, and a version that changes while it runs asks for one more."""

from __future__ import annotations

import time

import pytest

from lawgraph.db import version_cache


class _Data:
    """A database whose data version goes up when told (no queries)."""

    name = "warm-test"

    def __init__(self) -> None:
        self.version = 0

    def data_version(self) -> str:
        return str(self.version)


def _until(condition, seconds: float = 3.0) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.02)
    return condition()


@pytest.fixture
def warmed(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    runs: list[str] = []
    monkeypatch.setattr(version_cache, "WARM_UP_SETTLE", 0.3)
    monkeypatch.setattr(
        version_cache, "_warmers", [lambda s: runs.append(s.data_version())]
    )
    return runs


def test_fifty_new_versions_in_a_row_are_one_warm_up(warmed: list[str]) -> None:
    data = _Data()
    version_cache._version(data)  # the first version this process sees: no warm-up
    for _ in range(50):
        data.version += 1
        version_cache._version(data)
        time.sleep(0.004)
    assert _until(lambda: len(warmed) >= 1)
    time.sleep(0.6)
    assert 1 <= len(warmed) <= 2
    assert warmed[-1] == "50"  # of the newest data


def test_the_start_of_the_api_warms_up_at_once(warmed: list[str]) -> None:
    started = time.monotonic()
    version_cache.warm(_Data(), settle=0)
    assert _until(lambda: warmed == ["0"], 1.0)
    assert time.monotonic() - started < 0.3 + 0.2


def test_data_that_changes_during_a_warm_up_asks_for_one_more(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = _Data()
    runs: list[str] = []

    def warm_and_write(store) -> None:
        runs.append(store.data_version())
        if len(runs) == 1:
            store.version += 1  # a pipeline wrote while the warm-up ran

    monkeypatch.setattr(version_cache, "WARM_UP_SETTLE", 0.2)
    monkeypatch.setattr(version_cache, "_warmers", [warm_and_write])
    version_cache.warm(data, settle=0)
    assert _until(lambda: len(runs) == 2)
    time.sleep(0.5)
    assert runs == ["0", "1"]


def _starts(monkeypatch: pytest.MonkeyPatch, interval: float) -> list[float]:
    starts: list[float] = []
    monkeypatch.setattr(version_cache, "WARM_UP_SETTLE", 0.05)
    monkeypatch.setattr(version_cache, "WARM_UP_MIN_INTERVAL", interval)
    monkeypatch.setattr(
        version_cache, "_warmers", [lambda s: starts.append(time.monotonic())]
    )
    return starts


def test_a_warm_up_waits_for_the_least_time_after_the_one_before(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A poll that writes every half hour with a warm-up of minutes: the next waits until
    ``LAWGRAPH_WARM_UP_MIN_INTERVAL`` has gone by since the last began, for the newest data."""
    starts = _starts(monkeypatch, interval=0.8)
    data = _Data()
    version_cache.warm(data, settle=0)  # the start of the API: at once
    assert _until(lambda: len(starts) == 1, 1.0)
    data.version += 1
    version_cache.warm(data)
    assert not _until(lambda: len(starts) == 2, 0.5)  # held back
    assert _until(lambda: len(starts) == 2, 1.0)
    assert starts[1] - starts[0] >= 0.8


def test_without_a_least_time_a_warm_up_follows_when_the_data_stands_still(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    starts = _starts(monkeypatch, interval=0)
    data = _Data()
    version_cache.warm(data, settle=0)
    assert _until(lambda: len(starts) == 1, 1.0)
    data.version += 1
    version_cache.warm(data)
    assert _until(lambda: len(starts) == 2, 0.5)
    assert starts[1] - starts[0] < 0.4


def test_a_poll_is_noticed_without_a_request(
    warmed: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A poll that writes while nobody asks the API anything kept: the warm-up worker,
    waiting for nothing, reads the data version itself (``VERSION_POLL``) and warms up
    once it stands still."""
    monkeypatch.setattr(version_cache, "VERSION_POLL", 0.05)
    monkeypatch.setattr(version_cache, "VERSION_TTL", 0.0)
    data = _Data()
    version_cache.warm(data, settle=0)  # the start of the API
    assert _until(lambda: warmed == ["0"], 1.0)
    time.sleep(0.2)  # the worker has read the version it warmed
    data.version = 1  # a poll wrote; no request comes
    assert _until(lambda: warmed == ["0", "1"], 2.0)
