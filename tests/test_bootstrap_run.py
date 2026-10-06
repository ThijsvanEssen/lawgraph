"""``lawgraph bootstrap``: the steps of a plan in their lanes, marks, and the phases on record."""

from __future__ import annotations

import datetime as dt
import threading
from collections.abc import Callable
from typing import Any

import pytest

from lawgraph.commands import bootstrap, bootstrap_plan
from lawgraph.commands.bootstrap_plan import WRITE_LANE, Code, Mark, Plan, Step
from lawgraph.core.models import PipelineResult
from lawgraph.pipelines.base import STOP
from lawgraph.pipelines.command import State

CODE = Code("0.78.3", "build-0.78.3", "aaa")


@pytest.fixture
def marked(monkeypatch) -> dict[str, float]:
    """The marks the run writes (step -> seconds), without a database."""
    written: dict[str, float] = {}
    monkeypatch.setattr(
        bootstrap_plan,
        "mark_done",
        lambda store, label, seconds, code: written.__setitem__(label, seconds),
    )
    STOP.clear()
    return written


def _does(
    log: list[str],
    label: str,
    *,
    fails: bool = False,
    wait: threading.Event | None = None,
) -> Callable[..., PipelineResult]:
    def command(argv: list[str] | None = None) -> PipelineResult:
        if wait is not None:
            assert wait.wait(timeout=5), f"{label} waited in vain"
        log.append(label)
        if fails:
            raise RuntimeError(f"{label} broke")
        return PipelineResult(created=1)

    return command


def _run(
    plan: Plan, *, done: set[str] = frozenset(), jobs: int = 4, strict: bool = False
) -> dict[str, State]:  # type: ignore[assignment]
    outcomes = bootstrap._Run(plan, object(), CODE, set(done), jobs, strict).run()  # type: ignore[arg-type]
    return {o.label: o.state for o in outcomes}


def test_the_write_lane_takes_the_first_step_whose_wait_is_over(marked) -> None:
    """``normalize slow`` waits for a retrieve that is still running; the write lane does not
    wait with it but runs ``normalize fast`` first."""
    log: list[str] = []
    fast_done = threading.Event()

    def fast_normalize(argv: list[str] | None = None) -> PipelineResult:
        log.append("normalize fast")
        fast_done.set()
        return PipelineResult()

    plan = Plan(
        "730d",
        None,
        [
            Step("retrieve slow", "a", _does(log, "retrieve slow", wait=fast_done)),
            Step("retrieve fast", "b", _does(log, "retrieve fast")),
            Step(
                "normalize slow",
                WRITE_LANE,
                _does(log, "normalize slow"),
                after=("retrieve slow",),
            ),
            Step(
                "normalize fast", WRITE_LANE, fast_normalize, after=("retrieve fast",)
            ),
        ],
    )
    ended = _run(plan)
    assert set(ended.values()) == {State.OK}
    assert log.index("normalize fast") < log.index("normalize slow")
    assert set(marked) == set(ended)  # every step that ended ok is marked


def test_a_failed_step_leaves_out_what_waits_for_it_and_the_rest_goes_on(
    marked,
) -> None:
    log: list[str] = []
    plan = Plan(
        "730d",
        None,
        [
            Step("retrieve broken", "a", _does(log, "retrieve broken", fails=True)),
            Step("retrieve fine", "b", _does(log, "retrieve fine")),
            Step(
                "normalize broken",
                WRITE_LANE,
                _does(log, "normalize broken"),
                after=("retrieve broken",),
            ),
            Step(
                "semantic after",
                WRITE_LANE,
                _does(log, "semantic after"),
                after=("normalize broken",),
            ),
            Step(
                "normalize fine",
                WRITE_LANE,
                _does(log, "normalize fine"),
                after=("retrieve fine",),
            ),
        ],
    )
    outcomes = bootstrap._Run(plan, object(), CODE, set(), 4, False).run()  # type: ignore[arg-type]
    ended = {o.label: o.state for o in outcomes}
    assert ended == {
        "retrieve broken": State.FAILED,
        "retrieve fine": State.OK,
        "normalize broken": State.SKIPPED,
        "semantic after": State.SKIPPED,
        "normalize fine": State.OK,
    }
    assert "normalize broken" not in log and "semantic after" not in log
    notes = {o.label: o.result.notes for o in outcomes}
    assert notes["semantic after"] == ["not run: normalize broken did not end ok"]
    assert set(marked) == {"retrieve fine", "normalize fine"}


def test_strict_starts_nothing_after_a_failure(marked) -> None:
    log: list[str] = []
    plan = Plan(
        "730d",
        None,
        [
            Step("normalize a", WRITE_LANE, _does(log, "normalize a", fails=True)),
            Step("normalize b", WRITE_LANE, _does(log, "normalize b")),
        ],
    )
    assert _run(plan, strict=True) == {"normalize a": State.FAILED}
    assert log == ["normalize a"]


def test_a_step_that_is_done_is_not_run_again(marked) -> None:
    log: list[str] = []
    plan = Plan(
        "730d",
        None,
        [
            Step("retrieve a", "a", _does(log, "retrieve a")),
            Step(
                "normalize a",
                WRITE_LANE,
                _does(log, "normalize a"),
                after=("retrieve a",),
            ),
        ],
    )
    assert _run(plan, done={"retrieve a"}) == {"normalize a": State.OK}
    assert log == ["normalize a"]


def test_a_skip_variable_leaves_a_step_out_unmarked_and_the_next_runs(
    marked, monkeypatch
) -> None:
    monkeypatch.setenv("LAWGRAPH_SEMANTIC_SKIP_A", "true")
    log: list[str] = []
    plan = Plan(
        "730d",
        None,
        [
            Step("semantic a", WRITE_LANE, _does(log, "semantic a")),
            Step(
                "semantic b",
                WRITE_LANE,
                _does(log, "semantic b"),
                after=("semantic a",),
            ),
        ],
    )
    assert _run(plan) == {"semantic a": State.SKIPPED, "semantic b": State.OK}
    assert set(marked) == {"semantic b"}


def test_jobs_limits_the_retrieves_at_once_not_the_write_lane(marked) -> None:
    running, most = [0], [0]
    lock = threading.Lock()

    def retrieve(argv: list[str] | None = None) -> PipelineResult:
        with lock:
            running[0] += 1
            most[0] = max(most[0], running[0])
        threading.Event().wait(0.05)
        with lock:
            running[0] -= 1
        return PipelineResult()

    plan = Plan("730d", None, [Step(f"retrieve {n}", n, retrieve) for n in "abcd"])
    _run(plan, jobs=2)
    assert most[0] == 2


# ── the phases on record ─────────────────────────────────────────────────────


class _Watermarks:
    def __init__(self, mark: dt.datetime | None = None) -> None:
        self.mark = mark
        self.advanced: list[tuple[str, dt.datetime, dt.datetime | None]] = []

    def covered_until(self, store: Any, phase: str) -> dt.datetime | None:
        return self.mark

    def advance(
        self, store: Any, phase: str, *, began: dt.datetime, since: dt.datetime | None
    ) -> bool:
        self.advanced.append((phase, began, since))
        return True


def _mark(ended: str, seconds: float) -> Mark:
    return Mark(ended, seconds, CODE)


WINDOW = dt.datetime(2024, 10, 6, tzinfo=dt.timezone.utc)
PLAN = Plan(
    "730d",
    WINDOW,
    [
        Step("retrieve a", "a", _does([], "retrieve a")),
        Step("normalize a", WRITE_LANE, _does([], "normalize a")),
        Step("normalize b", WRITE_LANE, _does([], "normalize b")),
    ],
)


def test_a_phase_whose_steps_are_all_marked_is_on_record_from_its_first_start(
    monkeypatch,
) -> None:
    fake = _Watermarks()
    monkeypatch.setattr(bootstrap, "watermark", fake)
    monkeypatch.setattr(
        bootstrap_plan,
        "marks",
        lambda store: {
            "retrieve a": _mark("2026-10-06T10:00:00+00:00", 3600),
            "normalize a": _mark("2026-10-06T12:00:00+00:00", 60),
            "normalize b": _mark("2026-10-06T11:00:00+00:00", 600),
        },
    )
    bootstrap._record_phases(object(), PLAN)  # type: ignore[arg-type]
    assert fake.advanced == [
        ("retrieve", dt.datetime(2026, 10, 6, 9, tzinfo=dt.timezone.utc), WINDOW),
        ("normalize", dt.datetime(2026, 10, 6, 10, 50, tzinfo=dt.timezone.utc), None),
    ]


def test_a_phase_with_a_step_not_marked_is_not_on_record(monkeypatch) -> None:
    fake = _Watermarks()
    monkeypatch.setattr(bootstrap, "watermark", fake)
    monkeypatch.setattr(
        bootstrap_plan,
        "marks",
        lambda store: {"normalize a": _mark("2026-10-06T12:00:00+00:00", 60)},
    )
    bootstrap._record_phases(object(), PLAN)  # type: ignore[arg-type]
    assert fake.advanced == []


def test_a_later_mark_on_record_is_not_moved_back(monkeypatch) -> None:
    """expand-graph ends with a semantic all of its own, which records a later start."""
    fake = _Watermarks(dt.datetime(2026, 10, 7, tzinfo=dt.timezone.utc))
    monkeypatch.setattr(bootstrap, "watermark", fake)
    monkeypatch.setattr(
        bootstrap_plan,
        "marks",
        lambda store: {
            "retrieve a": _mark("2026-10-06T10:00:00+00:00", 3600),
            "normalize a": _mark("2026-10-06T12:00:00+00:00", 60),
            "normalize b": _mark("2026-10-06T11:00:00+00:00", 600),
        },
    )
    bootstrap._record_phases(object(), PLAN)  # type: ignore[arg-type]
    assert fake.advanced == []


# ── the command line ─────────────────────────────────────────────────────────


@pytest.fixture
def command(monkeypatch, marked) -> dict[str, Any]:
    """``bootstrap.main`` on a plan of three fake steps; what it ran and unmarked."""
    seen: dict[str, Any] = {"ran": [], "unmarked": []}
    plan = Plan(
        "730d",
        None,
        [
            Step("retrieve a", "a", _does(seen["ran"], "retrieve a")),
            Step(
                "normalize a",
                WRITE_LANE,
                _does(seen["ran"], "normalize a"),
                after=("retrieve a",),
            ),
            Step(
                "expand-graph",
                WRITE_LANE,
                _does(seen["ran"], "expand-graph"),
                after=("normalize a",),
            ),
        ],
    )

    def make_plan(window: str, since: Any, *, max_expand: int) -> Plan:
        seen["window"], seen["since"], seen["max_expand"] = window, since, max_expand
        return plan

    monkeypatch.setattr(bootstrap_plan, "make_plan", make_plan)
    monkeypatch.setattr(
        bootstrap_plan,
        "marks",
        lambda store: {"retrieve a": _mark("2026-10-06T10:00:00+00:00", 1)},
    )
    monkeypatch.setattr(
        bootstrap_plan, "unmark", lambda store, label: seen["unmarked"].append(label)
    )
    monkeypatch.setattr(bootstrap_plan, "current_code", lambda: CODE)
    monkeypatch.setattr(bootstrap, "GraphStore", lambda: object())
    monkeypatch.setattr(bootstrap, "_record_phases", lambda store, plan: None)
    return seen


def test_bootstrap_loads_a_two_year_window_by_default(command) -> None:
    bootstrap.main([])
    assert command["window"] == "730d"
    assert command["since"] is not None and command["max_expand"] == 5
    assert command["ran"] == ["normalize a", "expand-graph"]  # retrieve a is done


def test_skip_options_count_steps_as_done(command) -> None:
    bootstrap.main(["--window", "all", "--skip-expand"])
    assert command["since"] is None
    assert command["ran"] == ["normalize a"]


def test_redo_unmarks_a_step_of_the_plan(command) -> None:
    bootstrap.main(["--redo", "normalize a"])
    assert command["unmarked"] == ["normalize a"]


def test_redo_of_a_step_not_in_the_plan_is_refused(command, capsys) -> None:
    with pytest.raises(SystemExit) as exit_:
        bootstrap.main(["--redo", "normalize nothing"])
    assert exit_.value.code == 2
    assert "no step normalize nothing in the plan" in capsys.readouterr().err
    assert command["ran"] == []
