"""Steps in lanes: how ``<phase> all`` and ``lawgraph bootstrap`` run their steps.

A step runs a command under its label in a lane. Each lane runs one step at a time, in a
thread of its own (one lane runs in the calling thread, so Ctrl-C reaches its command). A step
waits for the steps of its ``after`` that are in the run; while it waits it takes none of the
*jobs* places. Two ways to choose the next step of a lane:

* ``in_order`` (``retrieve all``): the steps in the order given, those that wait last; the lane
  waits for its next step;
* else (``bootstrap``): the first step whose wait is over, so a lane does not stand still.

A step that waits for one that failed is not run (``skipped``, with a note), nor what waits
for it. ``strict`` starts no step after the first that failed. A ``LAWGRAPH_<PHASE>_SKIP_<NAME>``
leaves a step out. As each step ends a line says how and how far the run is; at the end a
table says how each ended, in the order of the steps.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Collection
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import dataclass

from lawgraph.config.settings import skip_step, skip_variable
from lawgraph.core.logging import current_step, get_logger, log_step
from lawgraph.core.time import format_duration
from lawgraph.pipelines.base import STOP
from lawgraph.pipelines.command import Main, Outcome, State, run_command
from lawgraph.pipelines.watchdog import watched

logger = get_logger(__name__)

PHASES = ("retrieve", "normalize", "semantic")  # the phases a skip variable names


@dataclass(frozen=True)
class Step:
    """One step of a run: what it runs, in which lane, after which steps."""

    label: str  # what one types after ``lawgraph``: retrieve tk, normalize tk, check
    lane: str
    command: Main
    argv: tuple[str, ...] = ()
    after: tuple[str, ...] = ()
    description: str = ""  # on its start line


OnOk = Callable[[Step, Outcome], None]


def run_steps(
    steps: list[Step],
    *,
    jobs: int = 1,
    in_order: bool = False,
    strict: bool = False,
    write_lane: str | None = None,
    done: Collection[str] = (),
    on_ok: OnOk | None = None,
) -> list[Outcome]:
    """Run *steps* in their lanes and return how each ended, in the order of *steps*.

    At most *jobs* steps run at once, not counting those of the *write_lane*. A step in
    *done* is not run and counts as ended ``ok``; *on_ok* is called for each step that ends
    ``ok``.
    """
    run = _Run(steps, jobs, in_order, strict, write_lane, done, on_ok)
    outcomes = run.run()
    for outcome in outcomes:
        took = (
            format_duration(outcome.seconds)
            if outcome.state is not State.SKIPPED
            else ""
        )
        notes = "; ".join(outcome.result.notes)
        logger.info(
            "  %-40s %8s  %s%s",
            outcome.label,
            took,
            outcome.state.value,
            f"  ({notes})" if notes else "",
        )
    return outcomes


def how_it_ended(outcome: Outcome) -> str:
    """``ok in 2h 03m, 1,234 created (a note)``."""
    if outcome.state is State.SKIPPED:
        return "skipped"
    notes = "; ".join(outcome.result.notes)
    return (
        f"{outcome.state.value} in {format_duration(outcome.seconds)}, "
        f"{outcome.result.summary()}{f' ({notes})' if notes else ''}"
    )


class _Run:
    """The steps of one run, each lane in a thread of its own."""

    def __init__(
        self,
        steps: list[Step],
        jobs: int,
        in_order: bool,
        strict: bool,
        write_lane: str | None,
        done: Collection[str],
        on_ok: OnOk | None,
    ) -> None:
        self.steps = steps
        self.in_order, self.strict = in_order, strict
        self.write_lane, self.on_ok = write_lane, on_ok
        labels = {step.label for step in steps}
        self.waits = {s.label: [a for a in s.after if a in labels] for s in steps}
        self.ended: dict[str, State] = dict.fromkeys(done, State.OK)
        self.left_out: set[str] = set()  # failed, or waits for one that was left out
        self.outcomes: dict[str, Outcome] = {}
        self.running: list[str] = []
        self.total = sum(step.label not in self.ended for step in steps)
        self.stopped = False
        self.changed = threading.Condition()
        self.places = threading.Semaphore(jobs)
        self.step = current_step()  # of the run: a thread of a lane has none of its own

    def run(self) -> list[Outcome]:
        lanes: dict[str, list[Step]] = {}
        for step in self.steps:
            lanes.setdefault(step.lane, []).append(step)
        if len(lanes) == 1:
            [(name, steps)] = lanes.items()
            self._lane(name, steps)
        else:
            self._side_by_side(lanes)
        return [self.outcomes[s.label] for s in self.steps if s.label in self.outcomes]

    def _side_by_side(self, lanes: dict[str, list[Step]]) -> None:
        with ThreadPoolExecutor(len(lanes), thread_name_prefix="lane") as pool:
            futures = [
                pool.submit(self._lane, name, steps) for name, steps in lanes.items()
            ]
            try:
                for future in futures:
                    future.result()
            except KeyboardInterrupt:
                # Ctrl-C reaches this thread only, and leaving the pool waits for the lanes.
                logger.warning(
                    "Interrupted: the running steps store what they have and stop."
                )
                STOP.set()
                with self.changed:
                    self.changed.notify_all()
                raise

    def _lane(self, lane: str, steps: list[Step]) -> None:
        with log_step(self.step):
            pending = [step for step in steps if step.label not in self.ended]
            if self.in_order:
                pending.sort(key=lambda step: bool(step.after))  # a stable sort
            while pending:
                step = self._next(lane, pending)
                if step is None:
                    return
                pending.remove(step)
                if step.label in self.left_out:
                    self._end(Outcome(step.label, State.SKIPPED), left_out=True)
                else:
                    self._end(self._run_step(step))

    def _next(self, lane: str, pending: list[Step]) -> Step | None:
        """The next step of *pending* whose wait is over, or that waits for a step that was
        left out; None once the run stops."""
        with self.changed:
            while not (self.stopped or STOP.is_set()):
                for step in pending[:1] if self.in_order else pending:
                    waits = self.waits[step.label]
                    if any(a in self.left_out for a in waits):
                        self.left_out.add(step.label)
                        return step
                    if all(a in self.ended for a in waits):
                        return step
                waiting = sorted(
                    {a for s in pending for a in self.waits[s.label]} - set(self.ended)
                )
                with watched(f"{lane} lane, waiting for {', '.join(waiting[:3])}"):
                    self.changed.wait()
        return None

    def _run_step(self, step: Step) -> Outcome:
        phase, _, name = step.label.partition(" ")
        if phase in PHASES and skip_step(phase, name):
            with log_step(step.label):
                logger.info("Skipped (%s).", skip_variable(phase, name))
            return Outcome(step.label, State.SKIPPED)
        with self.places if step.lane != self.write_lane else nullcontext():
            with self.changed:
                self.running.append(step.label)
            try:
                outcome = run_command(
                    step.label,
                    step.command,
                    list(step.argv),
                    description=step.description,
                )
            finally:
                with self.changed:
                    self.running.remove(step.label)
        if outcome.state is State.OK and self.on_ok is not None:
            self.on_ok(step, outcome)
        return outcome

    def _end(self, outcome: Outcome, *, left_out: bool = False) -> None:
        with self.changed:
            if left_out:
                step = next(s for s in self.steps if s.label == outcome.label)
                failed = [a for a in self.waits[step.label] if a in self.left_out]
                outcome.result.notes.append(
                    f"not run: {', '.join(failed)} did not end ok"
                )
            elif outcome.state is State.FAILED:
                self.left_out.add(outcome.label)
                if self.strict and not self.stopped:
                    self.stopped = True
                    logger.error("Stopping after '%s' (--strict).", outcome.label)
            self.ended[outcome.label] = outcome.state
            self.outcomes[outcome.label] = outcome
            running = f"; running: {', '.join(self.running)}" if self.running else ""
            logger.info(
                "%d of %d ended: %s %s%s.",
                len(self.outcomes),
                self.total,
                outcome.label,
                how_it_ended(outcome),
                running,
            )
            self.changed.notify_all()
