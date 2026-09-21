"""``retrieve all``: a Tweede Kamer window for full loads, and sources retrieved in parallel."""

from __future__ import annotations

import dataclasses
import threading
import time
from collections.abc import Callable
from typing import Any

import pytest

from lawgraph.core.models import PipelineResult
from lawgraph.pipelines import orchestration
from lawgraph.pipelines.command import Outcome, State, combined_result
from lawgraph.pipelines.orchestration import (
    _run_pipelines_in_lanes,
    retrieve_all,
    run_pipelines,
)
from lawgraph.sources import registry
from lawgraph.sources.registry import Pipeline, RetrieveCtx
from tests.fakes import PipelineStateFake

WINDOW = "2024-09-20T00:00:00+00:00"


# ── the Tweede Kamer window ──────────────────────────────────────────────────


def test_full_mode_without_a_window_loads_everything() -> None:
    ctx = RetrieveCtx(since="1d", mode="full")
    assert registry._windowed_argv(ctx) == ["--mode", "full", "--since", "1d"]
    assert registry._tk_dossiers_argv(ctx) == []


def test_full_mode_with_a_window_limits_only_the_tweede_kamer() -> None:
    ctx = RetrieveCtx(since="1d", mode="full", window=WINDOW)
    assert registry._windowed_argv(ctx) == ["--mode", "incremental", "--since", WINDOW]
    assert registry._tk_dossiers_argv(ctx) == ["--since", WINDOW]
    assert registry._mode_argv(ctx) == ["--mode", "full"]


def test_incremental_mode_ignores_the_window() -> None:
    ctx = RetrieveCtx(since="7d", mode="incremental", window=WINDOW)
    assert registry._windowed_argv(ctx) == ["--mode", "incremental", "--since", "7d"]
    assert registry._tk_dossiers_argv(ctx) == ["--since", "7d", "--skip-members"]


# ── lanes ────────────────────────────────────────────────────────────────────


def _step(
    name: str, lane: str, work: Callable[..., None], after: tuple[str, ...] = ()
) -> Pipeline:
    """The retrieve pipeline *name*: a command that does *work* and reports nothing."""

    def command(argv: list[str]) -> PipelineResult:
        work(argv)
        return PipelineResult()

    return Pipeline("retrieve", name, None, command, "", None, lane, after)


def _no_argv(pipeline: Pipeline) -> list[str]:
    return []


def _ended(outcomes: list[Outcome]) -> list[tuple[str, str]]:
    return [(o.label.removeprefix("retrieve "), o.state.value) for o in outcomes]


def test_lanes_run_side_by_side() -> None:
    barrier = threading.Barrier(3, timeout=5)

    def meet(argv: list[str]) -> None:
        barrier.wait()  # only passes when all three run at the same time

    steps = [_step(name, name, meet) for name in ("a", "b", "c")]
    assert _ended(_run_pipelines_in_lanes(steps, _no_argv, jobs=3)) == [
        ("a", "ok"),
        ("b", "ok"),
        ("c", "ok"),
    ]


def test_steps_of_one_lane_never_overlap_and_keep_their_order() -> None:
    running = 0
    peak = 0
    order: list[str] = []
    lock = threading.Lock()

    def make(name: str) -> Callable[..., None]:
        def main(argv: list[str]) -> None:
            nonlocal running, peak
            with lock:
                running += 1
                peak = max(peak, running)
                order.append(name)
            time.sleep(0.02)
            with lock:
                running -= 1

        return main

    steps = [_step(name, "one-server", make(name)) for name in ("first", "second")]
    _run_pipelines_in_lanes(steps, _no_argv, jobs=4)
    assert peak == 1
    assert order == ["first", "second"]


def test_results_keep_the_registry_order_and_a_failure_does_not_stop_the_others() -> (
    None
):
    def boom(argv: list[str]) -> None:
        raise RuntimeError("source down")

    steps = [
        _step("slow", "x", lambda argv: time.sleep(0.05)),
        _step("broken", "y", boom),
        _step("late", "z", lambda argv: None),
    ]
    assert _ended(_run_pipelines_in_lanes(steps, _no_argv, jobs=3)) == [
        ("slow", "ok"),
        ("broken", "failed"),
        ("late", "ok"),
    ]


def test_skip_variable_applies_in_parallel_mode(monkeypatch) -> None:
    monkeypatch.setenv("LAWGRAPH_RETRIEVE_SKIP_B", "true")
    calls: list[str] = []
    steps = [
        _step("a", "a", lambda argv: calls.append("a")),
        _step("b", "b", lambda argv: calls.append("b")),
    ]
    assert _ended(_run_pipelines_in_lanes(steps, _no_argv, jobs=2)) == [
        ("a", "ok"),
        ("b", "skipped"),
    ]
    assert calls == ["a"]


def test_a_failure_in_parallel_mode_fails_the_phase() -> None:
    def boom(argv: list[str]) -> None:
        raise RuntimeError("source down")

    outcomes = run_pipelines([_step("broken", "x", boom)], _no_argv, jobs=2)
    assert combined_result(outcomes).errors == ["retrieve broken failed"]


def test_one_job_stays_sequential_and_strict_still_stops() -> None:
    calls: list[str] = []

    def boom(argv: list[str]) -> None:
        calls.append("broken")
        raise RuntimeError("source down")

    steps = [
        _step("broken", "x", boom),
        _step("never", "y", lambda argv: calls.append("never")),
    ]
    outcomes = run_pipelines(steps, _no_argv, strict=True, jobs=1)
    assert calls == ["broken"] and [o.state for o in outcomes] == [State.FAILED]


# ── the command ──────────────────────────────────────────────────────────────


def _with_retrieve_commands(monkeypatch, command_of) -> None:
    """The registry, with the command of every retrieve pipeline replaced."""
    replaced = [
        dataclasses.replace(pipeline, command=command_of(pipeline))
        for pipeline in registry.PIPELINES["retrieve"]
    ]
    monkeypatch.setattr(
        orchestration, "PIPELINES", {**registry.PIPELINES, "retrieve": replaced}
    )


@pytest.fixture
def recorded(monkeypatch) -> dict[str, list[str]]:
    """Replace every retrieve pipeline of the registry by one that records its argv."""
    argvs: dict[str, list[str]] = {}
    _with_retrieve_commands(
        monkeypatch,
        lambda pipeline: (
            lambda argv: argvs.__setitem__(pipeline.name, argv) or PipelineResult()
        ),
    )
    return argvs


PRODUCING = ("tk", "rechtspraak", "staatscourant", "eerstekamer", "echr")


def test_the_window_reaches_the_sources_that_keep_producing(
    monkeypatch, recorded
) -> None:
    monkeypatch.setattr(orchestration, "ArangoStore", PipelineStateFake)
    retrieve_all(["--mode", "full", "--window", "2024-09-20"])
    for source in PRODUCING:
        assert recorded[source] == ["--mode", "incremental", "--since", WINDOW], source
    assert recorded["tk-dossiers"] == ["--since", WINDOW]
    assert "tk-content" not in recorded


def test_reference_sources_are_read_in_full_whatever_the_window(
    monkeypatch, recorded
) -> None:
    monkeypatch.setattr(orchestration, "ArangoStore", PipelineStateFake)
    retrieve_all(["--mode", "full", "--window", "2024-09-20"])
    assert recorded["bwb"] == ["--mode", "full"]
    assert WINDOW not in recorded["verdragenbank"]
    assert WINDOW not in recorded["eurlex"]


def test_window_all_loads_the_whole_history(monkeypatch, recorded) -> None:
    monkeypatch.setattr(orchestration, "ArangoStore", PipelineStateFake)
    retrieve_all(["--mode", "full", "--window", "all"])
    for source in PRODUCING:
        assert recorded[source][:2] == ["--mode", "full"], source
    assert recorded["tk-dossiers"] == []


def test_without_a_window_a_full_load_reads_two_years(monkeypatch, recorded) -> None:
    import datetime as dt

    monkeypatch.setattr(orchestration, "ArangoStore", PipelineStateFake)
    retrieve_all(["--mode", "full"])
    since = dt.datetime.fromisoformat(recorded["tk"][3])
    age = dt.datetime.now(dt.timezone.utc) - since
    assert dt.timedelta(days=729) < age < dt.timedelta(days=731)


def test_an_incremental_run_ignores_the_window(monkeypatch, recorded) -> None:
    monkeypatch.setattr(orchestration, "ArangoStore", PipelineStateFake)
    retrieve_all(["--since", "7d", "--window", "2024-09-20"])
    assert recorded["staatscourant"][:3] == ["--mode", "incremental", "--since"]
    assert WINDOW not in recorded["staatscourant"]


def test_a_bad_window_is_rejected() -> None:
    with pytest.raises(SystemExit) as exit_info:
        retrieve_all(["--window", "sometime"])
    assert exit_info.value.code == 2


def test_the_schema_is_created_once_before_the_threads_start(monkeypatch) -> None:
    events: list[str] = []

    def store() -> PipelineStateFake:
        events.append("store")
        return PipelineStateFake()

    monkeypatch.setattr(orchestration, "ArangoStore", store)
    _with_retrieve_commands(
        monkeypatch,
        lambda pipeline: lambda argv: events.append("step") or PipelineResult(),
    )
    retrieve_all(["--jobs", "3"])
    assert events[0] == "store"  # the store of the watermark: before any lane starts
    assert events.count("store") == 1
    assert "step" in events


def test_jobs_must_be_positive() -> None:
    with pytest.raises(SystemExit) as exit_info:
        retrieve_all(["--jobs", "0"])
    assert exit_info.value.code == 2


def test_sources_on_one_server_share_a_lane() -> None:
    lanes = {
        p.name: p.lane_id for p in registry.PIPELINES["retrieve"] if p.argv_for_all
    }
    assert lanes["tk"] == lanes["tk-dossiers"]
    koop = {"staatsblad", "staatscourant", "eerstekamer", "verdragenbank"}
    assert {lanes[name] for name in koop} == {registry.LANE_KOOP_REPOSITORY}
    assert len(set(lanes.values())) == len(lanes) - 1 - (len(koop) - 1)


# ── bootstrap ────────────────────────────────────────────────────────────────


def _bootstrap_retrieve_argv(monkeypatch, argv: list[str]) -> list[str]:
    from lawgraph.commands import bootstrap

    seen: dict[str, list[str]] = {}

    def record(label: str, command: Callable[..., Any], argv: list[str]) -> Outcome:
        seen[label] = argv
        return Outcome(label, State.OK)

    monkeypatch.setattr(bootstrap, "run_command", record)
    bootstrap.main(argv)
    return seen["retrieve all"]


def test_bootstrap_loads_a_two_year_window(monkeypatch) -> None:
    assert _bootstrap_retrieve_argv(monkeypatch, []) == [
        "--mode",
        "full",
        "--window",
        "730d",
        "--jobs",
        "6",  # one job per server
    ]


def test_bootstrap_passes_the_window_and_jobs_on(monkeypatch) -> None:
    argv = _bootstrap_retrieve_argv(monkeypatch, ["--window", "all", "--jobs", "2"])
    assert argv[argv.index("--window") + 1] == "all"
    assert argv[argv.index("--jobs") + 1] == "2"


# ── a step that reads what another source stored ─────────────────────────────


def test_a_step_waits_for_the_source_it_reads_and_goes_last_in_its_lane() -> None:
    import threading
    import time

    order: list[str] = []
    lock = threading.Lock()

    def main(name: str, seconds: float = 0.0) -> Callable[..., None]:
        def run(argv: list[str]) -> None:
            time.sleep(seconds)
            with lock:
                order.append(name)

        return run

    steps = [
        _step("bwb", "bwb", main("bwb", 0.2)),
        _step("staatsblad", "koop", main("staatsblad"), after=("bwb",)),
        _step("staatscourant", "koop", main("staatscourant")),
    ]
    # Two places and a waiting step: the wait must not take one of them.
    results = _run_pipelines_in_lanes(steps, _no_argv, jobs=2)

    assert [o.state for o in results] == [State.OK] * 3
    assert order == ["staatscourant", "bwb", "staatsblad"]


def test_a_failing_source_does_not_leave_its_reader_waiting() -> None:
    def fails(argv: list[str]) -> None:
        raise RuntimeError("SRU down")

    ran: list[str] = []
    steps = [
        _step("bwb", "bwb", fails),
        _step("staatsblad", "koop", lambda argv: ran.append("stb"), after=("bwb",)),
    ]
    assert _ended(_run_pipelines_in_lanes(steps, _no_argv, jobs=2)) == [
        ("bwb", "failed"),
        ("staatsblad", "ok"),
    ]
    assert ran == ["stb"]


def test_a_pipeline_comes_after_the_ones_it_reads() -> None:
    """``after`` names real pipelines that precede it, so ``--jobs 1`` is right too."""
    names = [p.name for p in registry.PIPELINES["retrieve"]]
    staatsblad = next(
        p for p in registry.PIPELINES["retrieve"] if p.name == "staatsblad"
    )
    assert staatsblad.after == ("bwb",)
    for pipeline in registry.PIPELINES["retrieve"]:
        for earlier in pipeline.after:
            assert names.index(earlier) < names.index(pipeline.name)


def test_by_default_every_server_has_its_own_job() -> None:
    from lawgraph.pipelines.orchestration import DEFAULT_RETRIEVE_JOBS

    lanes = {p.lane_id for p in registry.PIPELINES["retrieve"] if p.argv_for_all}
    assert DEFAULT_RETRIEVE_JOBS == len(lanes) == 6


def test_an_interrupt_stops_the_other_lanes_too() -> None:
    """Ctrl-C reaches the main thread only; the lanes fetched on for hours."""
    import time

    import pytest

    from lawgraph.pipelines.base import STOP

    looped: list[int] = []

    def interrupted(argv: list[str]) -> None:
        time.sleep(0.2)
        raise KeyboardInterrupt

    def long_running(argv: list[str]) -> None:
        # What RetrievePipelineBase._store_all does between two records.
        for number in range(10_000):
            if STOP.is_set():
                return
            looped.append(number)
            time.sleep(0.01)

    steps = [_step("a", "lane-a", interrupted), _step("b", "lane-b", long_running)]
    started = time.monotonic()
    try:
        with pytest.raises(KeyboardInterrupt):
            _run_pipelines_in_lanes(steps, _no_argv, jobs=2)
    finally:
        STOP.clear()
    assert time.monotonic() - started < 5 and len(looped) < 1_000


# ── filling gaps is a way to retrieve ────────────────────────────────────────


def test_gaps_mode_runs_the_sources_that_can_fetch_what_the_graph_lacks(
    monkeypatch, recorded
) -> None:
    """Every source fetches its own gaps, in lanes, under its own address: it was one
    `fill-gaps` that fetched them one after the other and normalized in between."""
    store = PipelineStateFake()
    monkeypatch.setattr(orchestration, "ArangoStore", lambda: store)
    result = retrieve_all(["--mode", "gaps"])

    assert result.errors == []
    assert (
        set(recorded)
        == {
            "bwb",
            "echr",
            "eurlex",
            "rechtspraak",
            "tk-content",  # a manual command otherwise: the text of papers is a gap by nature
            "verdragenbank",
        }
    )
    assert all(argv == ["--mode", "gaps"] for argv in recorded.values())
    assert store.state == {}  # a gaps run says nothing about a date: the mark stays


def test_two_gap_pipelines_on_one_host_share_its_lane() -> None:
    by_name = {p.name: p for p in registry.PIPELINES["retrieve"] if p.fills_gaps}
    assert by_name["tk-content"].lane_id == by_name["verdragenbank"].lane_id
