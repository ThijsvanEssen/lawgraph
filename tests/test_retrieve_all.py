"""``retrieve all``: a Tweede Kamer window for full loads, and sources retrieved in parallel."""

from __future__ import annotations

import dataclasses
import threading
import time
from collections.abc import Callable

import pytest

from lawgraph.pipelines import orchestration
from lawgraph.pipelines.orchestration import (
    _run_in_lanes,
    _run_phase,
    _Step,
    run_retrieve_all,
)
from lawgraph.sources import registry
from lawgraph.sources.registry import RetrieveCtx

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


def _step(name: str, lane: str, main: Callable[..., None]) -> _Step:
    return _Step(name, name, main, [], lane)


def test_lanes_run_side_by_side() -> None:
    barrier = threading.Barrier(3, timeout=5)

    def meet(argv: list[str]) -> None:
        barrier.wait()  # only passes when all three run at the same time

    steps = [_step(name, name, meet) for name in ("a", "b", "c")]
    assert _run_in_lanes("retrieve", steps, jobs=3) == [
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
    _run_in_lanes("retrieve", steps, jobs=4)
    assert peak == 1
    assert order == ["first", "second"]


def test_results_keep_the_registry_order_and_a_failure_does_not_stop_the_others() -> (
    None
):
    def boom(argv: list[str]) -> None:
        raise SystemExit(1)

    steps = [
        _step("slow", "x", lambda argv: time.sleep(0.05)),
        _step("broken", "y", boom),
        _step("late", "z", lambda argv: None),
    ]
    assert _run_in_lanes("retrieve", steps, jobs=3) == [
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
    assert _run_in_lanes("retrieve", steps, jobs=2) == [("a", "ok"), ("b", "skipped")]
    assert calls == ["a"]


def test_a_failure_in_parallel_mode_exits_1() -> None:
    def boom(argv: list[str]) -> None:
        raise SystemExit(1)

    with pytest.raises(SystemExit) as exit_info:
        _run_phase("retrieve", [_step("broken", "x", boom)], jobs=2)
    assert exit_info.value.code == 1


def test_one_job_stays_sequential_and_strict_still_stops() -> None:
    calls: list[str] = []

    def boom(argv: list[str]) -> None:
        calls.append("broken")
        raise SystemExit(1)

    steps = [
        _step("broken", "x", boom),
        _step("never", "y", lambda argv: calls.append("never")),
    ]
    with pytest.raises(SystemExit):
        _run_phase("semantic", steps, strict=True, jobs=1)
    assert calls == ["broken"]


# ── the command ──────────────────────────────────────────────────────────────


@pytest.fixture
def recorded(monkeypatch) -> dict[str, list[str]]:
    """Replace every retrieve step of the registry by one that records its argv."""
    argvs: dict[str, list[str]] = {}
    sources = [
        dataclasses.replace(
            source,
            retrieve_main=lambda argv, source_id=source.id: argvs.__setitem__(
                source_id, argv
            ),
        )
        if source.retrieve_main is not None
        else source
        for source in registry.SOURCES
    ]
    monkeypatch.setattr(orchestration, "SOURCES", sources)
    return argvs


PRODUCING = ("tk", "rechtspraak", "staatscourant", "eerstekamer", "echr")


def test_the_window_reaches_the_sources_that_keep_producing(
    monkeypatch, recorded
) -> None:
    monkeypatch.setattr(orchestration, "ArangoStore", lambda: object())
    run_retrieve_all(["--mode", "full", "--window", "2024-09-20"])
    for source in PRODUCING:
        assert recorded[source] == ["--mode", "incremental", "--since", WINDOW], source
    assert recorded["tk_dossiers"] == ["--since", WINDOW]
    assert "tk_content" not in recorded


def test_reference_sources_are_read_in_full_whatever_the_window(
    monkeypatch, recorded
) -> None:
    monkeypatch.setattr(orchestration, "ArangoStore", lambda: object())
    run_retrieve_all(["--mode", "full", "--window", "2024-09-20"])
    assert recorded["bwb"] == ["--mode", "full"]
    assert WINDOW not in recorded["verdragenbank"]
    assert WINDOW not in recorded["eurlex"]


def test_window_all_loads_the_whole_history(monkeypatch, recorded) -> None:
    monkeypatch.setattr(orchestration, "ArangoStore", lambda: object())
    run_retrieve_all(["--mode", "full", "--window", "all"])
    for source in PRODUCING:
        assert recorded[source][:2] == ["--mode", "full"], source
    assert recorded["tk_dossiers"] == []


def test_without_a_window_a_full_load_reads_two_years(monkeypatch, recorded) -> None:
    import datetime as dt

    monkeypatch.setattr(orchestration, "ArangoStore", lambda: object())
    run_retrieve_all(["--mode", "full"])
    since = dt.datetime.fromisoformat(recorded["tk"][3])
    age = dt.datetime.now(dt.timezone.utc) - since
    assert dt.timedelta(days=729) < age < dt.timedelta(days=731)


def test_an_incremental_run_ignores_the_window(monkeypatch, recorded) -> None:
    monkeypatch.setattr(orchestration, "ArangoStore", lambda: object())
    run_retrieve_all(["--since", "7d", "--window", "2024-09-20"])
    assert recorded["staatscourant"][:3] == ["--mode", "incremental", "--since"]
    assert WINDOW not in recorded["staatscourant"]


def test_a_bad_window_is_rejected() -> None:
    with pytest.raises(SystemExit) as exit_info:
        run_retrieve_all(["--window", "sometime"])
    assert exit_info.value.code == 2


def test_the_schema_is_created_once_before_the_threads_start(monkeypatch) -> None:
    events: list[str] = []
    monkeypatch.setattr(orchestration, "ArangoStore", lambda: events.append("store"))
    sources = [
        dataclasses.replace(s, retrieve_main=lambda argv: events.append("step"))
        if s.retrieve_main is not None
        else s
        for s in registry.SOURCES
    ]
    monkeypatch.setattr(orchestration, "SOURCES", sources)
    run_retrieve_all(["--jobs", "3"])
    assert events[0] == "store"
    assert events.count("store") == 1
    assert "step" in events


def test_one_job_needs_no_upfront_store(monkeypatch, recorded) -> None:
    def no_store() -> None:
        raise AssertionError("the sequential run opens its own stores")

    monkeypatch.setattr(orchestration, "ArangoStore", no_store)
    run_retrieve_all(["--jobs", "1"])
    assert recorded


def test_jobs_must_be_positive() -> None:
    with pytest.raises(SystemExit) as exit_info:
        run_retrieve_all(["--jobs", "0"])
    assert exit_info.value.code == 2


def test_sources_on_one_server_share_a_lane() -> None:
    lanes = {
        s.id: s.retrieve_lane or s.id
        for s in registry.SOURCES
        if s.retrieve_argv_builder is not None
    }
    assert lanes["tk"] == lanes["tk_dossiers"]
    koop = {"staatsblad", "staatscourant", "eerstekamer", "verdragenbank"}
    assert {lanes[source] for source in koop} == {registry.LANE_KOOP_REPOSITORY}
    assert len(set(lanes.values())) == len(lanes) - 1 - (len(koop) - 1)


# ── bootstrap ────────────────────────────────────────────────────────────────


def _bootstrap_retrieve_argv(monkeypatch, argv: list[str]) -> list[str]:
    from lawgraph.commands import bootstrap

    seen: dict[str, list[str]] = {}

    def record(name: str, main: Callable[..., None], phase_argv: list[str]) -> bool:
        seen[name] = phase_argv
        return True

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
        "4",
    ]


def test_bootstrap_passes_the_window_and_jobs_on(monkeypatch) -> None:
    argv = _bootstrap_retrieve_argv(monkeypatch, ["--window", "all", "--jobs", "2"])
    assert argv[argv.index("--window") + 1] == "all"
    assert argv[argv.index("--jobs") + 1] == "2"
