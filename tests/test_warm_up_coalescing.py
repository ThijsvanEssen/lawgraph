"""The warm-up of the API under a run of the pipelines, which raises the data version with
every statement that writes: at most one waits (the newest data), it starts once the version
stands still, and a version that changes while it runs asks for one more.

The warm-up runs on a clock the tests move by hand: a moment is a number, not a wait."""

from __future__ import annotations

import pytest

from lawgraph.db import version_cache
from tests.fakes import ManualClock, until

SETTLE = 0.3


class _Data:
    """A database whose data version goes up when told (no queries)."""

    name = "warm-test"

    def __init__(self) -> None:
        self.version = 0

    def data_version(self) -> str:
        return str(self.version)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> ManualClock:
    clock = ManualClock()
    monkeypatch.setattr(version_cache, "_clock", clock)
    monkeypatch.setattr(version_cache, "WARM_UP_SETTLE", SETTLE)
    return clock


def _warmers(monkeypatch: pytest.MonkeyPatch, warmer) -> None:
    monkeypatch.setattr(version_cache, "_warmers", [warmer])


@pytest.fixture
def warmed(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    runs: list[str] = []
    _warmers(monkeypatch, lambda s: runs.append(s.data_version()))
    return runs


def _done(data: _Data) -> bool:
    return not version_cache.computing(data)


def test_fifty_new_versions_in_a_row_are_one_warm_up(
    clock: ManualClock, warmed: list[str]
) -> None:
    data = _Data()
    version_cache._version(data)  # the first version this process sees: no warm-up
    for _ in range(50):
        data.version += 1
        version_cache._version(data)
    clock.move_to_wait(SETTLE)  # the version stood still for the settle
    assert until(lambda: bool(warmed) and _done(data))
    assert warmed == ["50"]  # of the newest data


def test_the_start_of_the_api_warms_up_at_once(
    clock: ManualClock, warmed: list[str]
) -> None:
    data = _Data()
    version_cache.warm(data, settle=0)
    assert until(lambda: bool(warmed) and _done(data))  # the clock never moved
    assert warmed == ["0"]


def test_data_that_changes_during_a_warm_up_asks_for_one_more(
    clock: ManualClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = _Data()
    runs: list[str] = []

    def warm_and_write(store) -> None:
        runs.append(store.data_version())
        if len(runs) == 1:
            store.version += 1  # a pipeline wrote while the warm-up ran

    _warmers(monkeypatch, warm_and_write)
    version_cache.warm(data, settle=0)
    clock.move_to_wait(SETTLE)  # the next one settles first
    assert until(lambda: len(runs) == 2 and _done(data))
    assert runs == ["0", "1"]


def _starts(
    monkeypatch: pytest.MonkeyPatch, clock: ManualClock, interval: float
) -> list[float]:
    starts: list[float] = []
    monkeypatch.setattr(version_cache, "WARM_UP_MIN_INTERVAL", interval)
    _warmers(monkeypatch, lambda s: starts.append(clock.now()))
    return starts


def test_a_warm_up_waits_for_the_least_time_after_the_one_before(
    clock: ManualClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A poll that writes every half hour with a warm-up of minutes: the next waits until
    ``LAWGRAPH_WARM_UP_MIN_INTERVAL`` has gone by since the last began, for the newest data."""
    interval = 4 * SETTLE
    starts = _starts(monkeypatch, clock, interval)
    data = _Data()
    version_cache.warm(data, settle=0)  # the start of the API: at once
    assert until(lambda: starts == [0.0])
    data.version += 1
    version_cache.warm(data)
    clock.move_to_wait(interval)  # not the settle: it is held back
    assert until(lambda: len(starts) == 2)
    assert starts == [0.0, pytest.approx(interval)]


def test_without_a_least_time_a_warm_up_follows_when_the_data_stands_still(
    clock: ManualClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    starts = _starts(monkeypatch, clock, interval=0)
    data = _Data()
    version_cache.warm(data, settle=0)
    assert until(lambda: starts == [0.0])
    data.version += 1
    version_cache.warm(data)
    clock.move_to_wait(SETTLE)
    assert until(lambda: len(starts) == 2)
    assert starts == [0.0, pytest.approx(SETTLE)]


def test_a_poll_is_noticed_without_a_request(
    clock: ManualClock, warmed: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A poll that writes while nobody asks the API anything kept: the warm-up worker,
    waiting for nothing, reads the data version itself (``VERSION_POLL``) and warms up
    once it stands still."""
    poll = SETTLE / 6
    monkeypatch.setattr(version_cache, "VERSION_POLL", poll)
    data = _Data()
    version_cache.warm(data, settle=0)  # the start of the API
    assert until(lambda: warmed == ["0"])
    clock.move_to_wait(poll)  # the worker reads the version it warmed
    assert clock.waits_until(2 * poll)
    data.version = 1  # a poll wrote; no request comes
    clock.move_to_wait(2 * poll)  # the worker reads the new one
    clock.move_to_wait(2 * poll + SETTLE)
    assert until(lambda: warmed == ["0", "1"])
