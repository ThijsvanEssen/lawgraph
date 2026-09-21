"""``--since last``: a phase goes on where its last complete run began, whenever that was."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from lawgraph.core.time import RELATIVE_SINCE_OVERLAP
from lawgraph.pipelines import orchestration, watermark
from lawgraph.pipelines.command import Outcome, State
from tests.fakes import PipelineStateFake

UTC = dt.timezone.utc
MONDAY = dt.datetime(2026, 9, 14, 6, 0, tzinfo=UTC)
THURSDAY = dt.datetime(2026, 9, 17, 6, 0, tzinfo=UTC)


_Store = PipelineStateFake


def test_a_complete_run_is_remembered_by_when_it_began() -> None:
    store = _Store()
    assert watermark.covered_until(store, "retrieve") is None
    assert watermark.advance(store, "retrieve", began=MONDAY, since=None)
    assert watermark.covered_until(store, "retrieve") == MONDAY
    assert watermark.covered_until(store, "normalize") is None  # one per phase


def test_a_run_that_leaves_a_hole_does_not_move_the_mark() -> None:
    """Monday is on record; a run on Thursday with `--since 1d` skipped two days."""
    store = _Store()
    watermark.advance(store, "retrieve", began=MONDAY, since=None)
    since = THURSDAY - dt.timedelta(days=1)
    assert not watermark.advance(store, "retrieve", began=THURSDAY, since=since)
    assert watermark.covered_until(store, "retrieve") == MONDAY

    caught_up = watermark.since_last(store, "retrieve")
    assert caught_up == MONDAY - RELATIVE_SINCE_OVERLAP
    assert watermark.advance(store, "retrieve", began=THURSDAY, since=caught_up)
    assert watermark.covered_until(store, "retrieve") == THURSDAY


def test_last_without_a_run_on_record_is_refused() -> None:
    with pytest.raises(watermark.NothingOnRecord, match="normalize all.*with a date"):
        watermark.since_last(_Store(), "normalize")


# ── in the `<phase> all` commands ────────────────────────────────────────────


@pytest.fixture
def phase(monkeypatch) -> dict[str, Any]:
    seen: dict[str, Any] = {"store": _Store(), "outcomes": [Outcome("a", State.OK)]}

    def run_pipelines(pipelines: list[Any], argv_of: Any, **kw: Any) -> list[Outcome]:
        seen["argv"] = [argv_of(pipeline) for pipeline in pipelines]
        return seen["outcomes"]

    monkeypatch.setattr(orchestration, "ArangoStore", lambda: seen["store"])
    monkeypatch.setattr(orchestration, "run_pipelines", run_pipelines)
    return seen


def test_normalize_all_since_last_starts_where_the_last_complete_run_began(
    phase: dict[str, Any],
) -> None:
    watermark.advance(phase["store"], "normalize", began=MONDAY, since=None)
    orchestration.normalize_all(["--since", "last"])
    expected = (MONDAY - RELATIVE_SINCE_OVERLAP).isoformat()
    assert all(argv == ["--since", expected] for argv in phase["argv"])
    assert watermark.covered_until(phase["store"], "normalize") > MONDAY


def test_a_run_with_a_skipped_step_does_not_move_the_mark(
    phase: dict[str, Any],
) -> None:
    watermark.advance(phase["store"], "semantic", began=MONDAY, since=None)
    phase["outcomes"] = [Outcome("a", State.OK), Outcome("b", State.SKIPPED)]
    orchestration.semantic_all([])
    assert watermark.covered_until(phase["store"], "semantic") == MONDAY


def test_retrieve_all_in_full_mode_covers_everything(phase: dict[str, Any]) -> None:
    orchestration.retrieve_all(["--mode", "full", "--jobs", "1"])
    assert watermark.covered_until(phase["store"], "retrieve") is not None


def test_a_full_load_with_a_window_read_since_the_window(phase: dict[str, Any]) -> None:
    """Not since ``--since`` (a day by default): a mark on record before the window stays."""
    watermark.advance(phase["store"], "retrieve", began=MONDAY, since=None)
    long_ago = MONDAY - dt.timedelta(days=30)
    orchestration.retrieve_all(
        ["--mode", "full", "--window", long_ago.isoformat(), "--jobs", "1"]
    )
    assert watermark.covered_until(phase["store"], "retrieve") > MONDAY
