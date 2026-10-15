"""When each step of ``retrieve all`` and of ``bootstrap`` starts, on a clock of its own.

Every command of the registry is replaced by one that takes a fixed number of ticks and
blocks until the test ends it. The test knows when every lane thread waits (the scheduler's
own ``Condition``, ``Event`` and ``Semaphore`` count their waiters), so it ends one command
at a time, the first due, once nothing else can happen: the run is the same on every
machine. What it records, when each step started and ended, must be what the rules of the
lanes give (``_expected``):

* ``retrieve all``: a lane per server runs its pipelines in registry order, those that wait
  for another (``after``) last, each one only once what it waits for has ended, failed or
  not;
* ``bootstrap``: a lane per server and the write lane; each takes the first of its steps
  whose wait is over, and a step that waits for one that failed is left out, as is what
  waits for that.
"""

from __future__ import annotations

import dataclasses
import sys
import threading
import time
import types
import zlib
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from lawgraph.commands import bootstrap, bootstrap_plan
from lawgraph.commands.bootstrap_plan import Plan
from lawgraph.core.models import PipelineResult
from lawgraph.pipelines import orchestration
from lawgraph.sources import registry
from tests.fakes import PATIENCE, PipelineStateFake, patch_pipeline_state

SCHEDULERS = (orchestration, bootstrap)  # the modules whose threads the test counts

Trace = dict[str, tuple[int, int]]  # step -> (start, end), in ticks


SLOW: set[str] = set()  # steps that take long, so that what waits for them must wait


def _ticks(label: str) -> int:
    """How long *label* takes: 1 to 5 ticks, fixed per step, or 40 when it is slow."""
    return 40 if label in SLOW else 1 + zlib.crc32(label.encode()) % 5


# ── threads that say when they wait ──────────────────────────────────────────


class _Count:
    """The lane threads that run, and how many of them wait."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.active = 0
        self.waiting = 0

    def add(self, *, active: int = 0, waiting: int = 0) -> None:
        with self.lock:
            self.active += active
            self.waiting += waiting

    def settled(self) -> bool:
        """Every lane thread waits: nothing happens until the test ends a command."""
        with self.lock:
            return self.active > 0 and self.active == self.waiting


COUNT = _Count()


class _Condition(threading.Condition):
    """A waiter counts as waiting until it is notified, not until it runs again."""

    def wait(self, timeout: float | None = None) -> bool:
        COUNT.add(waiting=1)
        return super().wait(timeout)

    def notify(self, n: int = 1) -> None:
        COUNT.add(waiting=-min(n, len(self._waiters)))  # type: ignore[attr-defined]
        super().notify(n)


class _Event(threading.Event):
    def __init__(self) -> None:
        super().__init__()
        self._cond = _Condition(threading.Lock())


class _Semaphore(threading.Semaphore):
    def __init__(self, value: int = 1) -> None:
        super().__init__(value)
        self._cond = _Condition(threading.Lock())


class _Executor(ThreadPoolExecutor):
    """A lane counts from the moment it is submitted until it has returned; the thread that
    submits them counts until it waits for the first result, so a lane that waits before
    the next is submitted does not settle the run."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.submitting = True
        COUNT.add(active=1)

    def submitted(self) -> None:
        if self.submitting:
            self.submitting = False
            COUNT.add(active=-1)

    def submit(self, fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
        COUNT.add(active=1)

        def counted() -> Any:
            try:
                return fn(*args, **kwargs)
            finally:
                COUNT.add(active=-1)

        future = super().submit(counted)
        result = future.result

        def waited(timeout: float | None = None) -> Any:
            self.submitted()
            return result(timeout)

        future.result = waited  # type: ignore[method-assign]
        return future


COUNTED_THREADING = types.SimpleNamespace(
    Condition=_Condition, Event=_Event, Semaphore=_Semaphore, Lock=threading.Lock
)


# ── the clock ────────────────────────────────────────────────────────────────


class _Clock:
    """Commands that take ``_ticks`` and end when the clock reaches their end."""

    def __init__(self, failing: set[str]) -> None:
        self.failing = failing
        self.now = 0
        self.lock = threading.Lock()
        self.running: dict[str, tuple[int, threading.Event]] = {}
        self.trace: Trace = {}

    def command(self, label: str) -> Callable[..., PipelineResult]:
        def run(argv: list[str] | None = None) -> PipelineResult:
            ends = threading.Event()
            with self.lock:
                self.trace[label] = (self.now, self.now + _ticks(label))
                self.running[label] = (self.now + _ticks(label), ends)
            COUNT.add(waiting=1)
            assert ends.wait(PATIENCE), f"{label} never ended"
            if label in self.failing:
                raise RuntimeError(f"{label} broke")
            return PipelineResult()

        return run

    def drive(self, run: Callable[[], Any]) -> Trace:
        """Run *run* in a thread and end its commands one by one, the first due first."""
        errors: list[BaseException] = []

        def target() -> None:
            try:
                run()
            except BaseException as exc:  # noqa: BLE001 — reported in the test thread
                errors.append(exc)

        thread = threading.Thread(target=target)
        thread.start()
        while True:
            assert _until(lambda: not thread.is_alive() or COUNT.settled()), "stuck"
            if not thread.is_alive():
                break
            with self.lock:
                assert self.running, "every lane waits and no command runs"
                label = min(
                    self.running, key=lambda name: (self.running[name][0], name)
                )
                self.now, ends = self.running.pop(label)
            COUNT.add(waiting=-1)
            ends.set()
        if errors:
            raise errors[0]
        return self.trace


def _until(condition: Callable[[], bool]) -> bool:
    deadline = time.monotonic() + PATIENCE
    while not condition():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.0002)
    return True


@pytest.fixture
def counted(monkeypatch: pytest.MonkeyPatch) -> None:
    global COUNT
    COUNT = _Count()
    for module in SCHEDULERS:
        monkeypatch.setattr(module, "threading", COUNTED_THREADING)
        monkeypatch.setattr(module, "ThreadPoolExecutor", _Executor)


# ── the rules ────────────────────────────────────────────────────────────────


Lanes = dict[str, list[tuple[str, tuple[str, ...]]]]  # lane -> [(step, after)]


def _expected(
    lanes: Lanes, failing: set[str], *, in_order: bool, leave_out: bool
) -> Trace:
    """When each step starts and ends by the rules: *in_order*, a lane waits for its next
    step; else it takes the first whose wait is over. *leave_out*: a step that waits for
    one that failed or was left out is left out."""
    steps = {label for lane in lanes.values() for label, _ in lane}
    pending = {name: list(lane) for name, lane in lanes.items()}
    ended: set[str] = set()
    left_out: set[str] = set()
    busy: dict[str, tuple[int, str]] = {}  # lane -> (end, step)
    trace: Trace = {}
    now = 0

    def take() -> None:
        taken = True
        while taken:
            taken = False
            for name, lane in pending.items():
                if name in busy:
                    continue
                for label, after in lane[:1] if in_order else lane:
                    waits = [a for a in after if a in steps]
                    if leave_out and any(a in left_out for a in waits):
                        lane.remove((label, after))
                        left_out.add(label)
                        ended.add(label)
                    elif all(a in ended for a in waits):
                        lane.remove((label, after))
                        trace[label] = (now, now + _ticks(label))
                        busy[name] = (now + _ticks(label), label)
                    else:
                        continue
                    taken = True
                    break

    take()
    while busy:
        name = min(busy, key=lambda lane: busy[lane])
        now, label = busy.pop(name)
        ended.add(label)
        if label in failing:
            left_out.add(label)
        take()
    assert not any(pending.values()), pending
    return trace


# ── retrieve all ─────────────────────────────────────────────────────────────


# what other retrieves wait for (``after``): slow, the waits decide when those start
WAITED_FOR = {"retrieve bwb", "retrieve tk-dossiers", "retrieve rijksoverheid"}

RETRIEVE_RUNS = {
    "incremental": ["--since", "2026-10-01"],
    "full": ["--mode", "full", "--window", "2024-09-20"],
    "gaps": ["--mode", "gaps"],
}


@pytest.mark.parametrize(
    ("failing", "slow"),
    [(set(), set()), ({"retrieve bwb"}, set()), (set(), WAITED_FOR)],
    ids=["ok", "bwb-fails", "slow-sources"],
)
@pytest.mark.parametrize("mode", list(RETRIEVE_RUNS))
def test_retrieve_all_starts_each_pipeline_when_its_lane_and_wait_allow(
    monkeypatch: pytest.MonkeyPatch,
    counted: None,
    mode: str,
    failing: set[str],
    slow: set[str],
) -> None:
    patch_pipeline_state(monkeypatch)
    monkeypatch.setattr(orchestration, "GraphStore", PipelineStateFake)
    monkeypatch.setattr(sys.modules[__name__], "SLOW", slow)
    clock = _Clock(failing)
    pipelines = [
        dataclasses.replace(p, command=clock.command(p.address))
        for p in registry.PIPELINES["retrieve"]
    ]
    monkeypatch.setattr(
        orchestration, "PIPELINES", {**registry.PIPELINES, "retrieve": pipelines}
    )
    trace = clock.drive(lambda: orchestration.retrieve_all(RETRIEVE_RUNS[mode]))

    lanes: Lanes = {}
    run = [p for p in pipelines if mode != "gaps" or p.fills_gaps]
    for p in sorted(run, key=lambda p: bool(p.after)):  # a stable sort: waiting last
        lanes.setdefault(p.lane_id, []).append(
            (p.address, tuple(f"retrieve {a}" for a in p.after))
        )
    assert trace == _expected(lanes, failing, in_order=True, leave_out=False)
    assert len({start for start, _ in trace.values()}) < len(trace)  # side by side


# ── bootstrap ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("failing", "slow"),
    [(set(), set()), ({"retrieve bwb"}, set()), (set(), WAITED_FOR)],
    ids=["ok", "bwb-fails", "slow-sources"],
)
def test_bootstrap_starts_each_step_when_its_lane_and_wait_allow(
    monkeypatch: pytest.MonkeyPatch, counted: None, failing: set[str], slow: set[str]
) -> None:
    monkeypatch.setattr(sys.modules[__name__], "SLOW", slow)
    clock = _Clock(failing)
    plans: list[Plan] = []
    make_plan = bootstrap_plan.make_plan

    def timed_plan(*args: Any, **kwargs: Any) -> Plan:
        plan = make_plan(*args, **kwargs)
        steps = [
            dataclasses.replace(s, command=clock.command(s.label)) for s in plan.steps
        ]
        plans.append(dataclasses.replace(plan, steps=steps))
        return plans[-1]

    monkeypatch.setattr(bootstrap_plan, "make_plan", timed_plan)
    monkeypatch.setattr(bootstrap_plan, "marks", lambda store: {})
    monkeypatch.setattr(bootstrap_plan, "mark_done", lambda *args: None)
    monkeypatch.setattr(bootstrap_plan, "current_code", lambda: None)
    monkeypatch.setattr(bootstrap, "GraphStore", lambda: object())
    monkeypatch.setattr(bootstrap, "_record_phases", lambda store, plan: None)
    trace = clock.drive(lambda: bootstrap.main(["--window", "2024-10-06"]))

    lanes = {
        name: [(s.label, s.after) for s in steps]
        for name, steps in plans[0].lanes().items()
    }
    expected = _expected(lanes, failing, in_order=False, leave_out=True)
    assert trace == expected
    assert len({start for start, _ in trace.values()}) < len(trace)  # side by side
    if failing:
        assert "check" not in trace and "normalize bwb" not in trace
