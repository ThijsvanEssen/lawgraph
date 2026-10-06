"""``lawgraph bootstrap``: fill an empty database, as planned in ``commands/bootstrap_plan.py``.

The retrieves run in a lane per server and every step that writes the graph in one write
lane, one at a time; each lane takes the first of its steps whose wait is over, so a
normalize runs as soon as what it reads is there (``normalize tk`` while Rechtspraak is
still being retrieved). The producing sources (Tweede Kamer, Rechtspraak, Staatscourant,
Eerste Kamer, ECHR) load a window (``--window``, default 730d; ``all`` loads their whole
history), the reference sources load in full, ``--jobs`` retrieves at most that many sources
at once.

A step that ends ``ok`` is marked with the code it ran on; a build started again skips the
marked steps (``--redo STEP`` runs one again). A step that fails leaves the steps that wait
for it out and the others go on, unless ``--strict``; the exit code is 1 when any step
failed. When every step of a phase is marked, the phase is on record for ``--since last``
from the moment its first step began. A ``LAWGRAPH_<PHASE>_SKIP_<NAME>`` leaves a step out
without a mark.

``--plan`` prints the plan instead: its window, every step in its lane with what it waits
for, and which steps are done, on which code.
"""

from __future__ import annotations

import argparse
import datetime as dt
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from lawgraph.commands import bootstrap_plan
from lawgraph.commands.bootstrap_plan import WRITE_LANE, Code, Plan, Step
from lawgraph.config.settings import skip_step, skip_variable
from lawgraph.core.logging import current_step, get_logger, log_step
from lawgraph.core.models import PipelineResult
from lawgraph.db import GraphStore
from lawgraph.pipelines import watermark
from lawgraph.pipelines.base import STOP
from lawgraph.pipelines.command import Outcome, State, combined_result, run_command
from lawgraph.pipelines.orchestration import (
    DEFAULT_RETRIEVE_JOBS,
    DEFAULT_WINDOW,
    how_it_ended,
    window_since,
)
from lawgraph.pipelines.watchdog import watched

logger = get_logger(__name__)

PHASES = ("retrieve", "normalize", "semantic")


def main(argv: list[str] | None = None) -> PipelineResult:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.jobs < 1:
        parser.error("--jobs must be at least 1")
    try:
        since = window_since(args.window)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    plan = bootstrap_plan.make_plan(args.window, since, max_expand=args.max_expand)
    labels = {step.label for step in plan.steps}
    if unknown := [label for label in args.redo if label not in labels]:
        parser.error(f"--redo: no step {', '.join(unknown)} in the plan (see --plan)")

    store = GraphStore()  # before any lane starts: the schema is made once
    code = bootstrap_plan.current_code()
    if args.plan:
        print(bootstrap_plan.describe(plan, bootstrap_plan.marks(store), code))
        return PipelineResult()

    for label in args.redo:
        bootstrap_plan.unmark(store, label)
    done = set(bootstrap_plan.marks(store))
    counted = {
        step.label
        for step in plan.steps
        if (args.skip_retrieve and step.label.startswith("retrieve "))
        or (args.skip_expand and step.label == "expand-graph")
    }
    logger.info(
        "Window %s; code %s; %d of %d steps done, %d counted as done.",
        args.window,
        code,
        len(done & labels),
        len(labels),
        len(counted - done),
    )
    outcomes = _Run(plan, store, code, done | counted, args.jobs, args.strict).run()
    _record_phases(store, plan)
    return combined_result(outcomes)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fill an empty LawGraph database.")
    parser.add_argument(
        "--window",
        default=DEFAULT_WINDOW,
        metavar="DATE",
        help="Load what the producing sources changed since then (default: %(default)s); "
        "'all' loads their whole history.",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=DEFAULT_RETRIEVE_JOBS,
        metavar="N",
        help="Sources to retrieve at the same time (default: %(default)s, one per server).",
    )
    parser.add_argument(
        "--max-expand",
        type=int,
        default=bootstrap_plan.DEFAULT_MAX_EXPAND,
        metavar="N",
        help="Rounds of expand-graph (default: %(default)s).",
    )
    parser.add_argument(
        "--redo",
        action="append",
        default=[],
        metavar="STEP",
        help="Run this step again although it is marked done (repeatable), e.g. "
        "--redo 'semantic staatscourant'.",
    )
    parser.add_argument(
        "--skip-retrieve",
        action="store_true",
        help="Count every retrieve step as done (the raw records are there).",
    )
    parser.add_argument(
        "--skip-expand", action="store_true", help="Count expand-graph as done."
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Start no step after the first that failed.",
    )
    parser.add_argument(
        "--plan",
        action="store_true",
        help="Print the plan of the build (lanes, steps, what each waits for, what is "
        "done) and run nothing.",
    )
    return parser


class _Run:
    """The steps of a plan that are not done, each lane in a thread of its own."""

    def __init__(
        self,
        plan: Plan,
        store: GraphStore,
        code: Code,
        done: set[str],
        jobs: int,
        strict: bool,
    ) -> None:
        self.plan, self.store, self.code, self.strict = plan, store, code, strict
        # how each step ended; a step that is done counts as ok
        self.ended: dict[str, State] = dict.fromkeys(done, State.OK)
        self.blocked: set[str] = set()  # failed, or waits for one that did
        self.outcomes: list[Outcome] = []
        self.total = sum(step.label not in done for step in plan.steps)
        self.stopped = False
        self.changed = threading.Condition()
        self.places = threading.Semaphore(jobs)  # retrieve steps at the same time
        self.step = current_step()  # of the build: a thread of a lane has none

    def run(self) -> list[Outcome]:
        lanes = self.plan.lanes()
        with ThreadPoolExecutor(len(lanes), thread_name_prefix="lane") as pool:
            futures = [
                pool.submit(self._lane, name, steps) for name, steps in lanes.items()
            ]
            try:
                for future in futures:
                    future.result()
            except KeyboardInterrupt:
                logger.warning(
                    "Interrupted: the running steps store what they have and stop."
                )
                STOP.set()
                with self.changed:
                    self.changed.notify_all()
                raise
        for outcome in self.outcomes:
            logger.info("  %-40s %s", outcome.label, how_it_ended(outcome))
        return self.outcomes

    def _lane(self, lane: str, steps: list[Step]) -> None:
        with log_step(self.step):
            pending = [step for step in steps if step.label not in self.ended]
            while pending:
                step = self._next(lane, pending)
                if step is None:
                    return
                pending.remove(step)
                if step.label in self.blocked:
                    self._end(Outcome(step.label, State.SKIPPED), blocked=True)
                    continue
                self._end(self._run_step(step))

    def _next(self, lane: str, pending: list[Step]) -> Step | None:
        """The first of *pending* whose wait is over, or that waits for a failed step."""
        with self.changed:
            while not (self.stopped or STOP.is_set()):
                for step in pending:
                    if any(a in self.blocked for a in step.after):
                        self.blocked.add(step.label)
                        return step
                    if all(a in self.ended for a in step.after):
                        return step
                waiting = sorted(
                    {a for s in pending for a in s.after} - set(self.ended)
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
        if step.lane == WRITE_LANE:
            outcome = run_command(step.label, step.command, list(step.argv))
        else:
            with self.places:
                outcome = run_command(step.label, step.command, list(step.argv))
        if outcome.state is State.OK:
            bootstrap_plan.mark_done(self.store, step.label, outcome.seconds, self.code)
        return outcome

    def _end(self, outcome: Outcome, *, blocked: bool = False) -> None:
        with self.changed:
            if blocked:
                failed = [
                    a for a in self._step(outcome.label).after if a in self.blocked
                ]
                outcome.result.notes.append(
                    f"not run: {', '.join(failed)} did not end ok"
                )
            elif outcome.state is State.FAILED:
                self.blocked.add(outcome.label)
                self.stopped = self.stopped or self.strict
            self.ended[outcome.label] = outcome.state
            self.outcomes.append(outcome)
            logger.info(
                "%d of %d ended: %s %s.",
                len(self.outcomes),
                self.total,
                outcome.label,
                how_it_ended(outcome),
            )
            self.changed.notify_all()

    def _step(self, label: str) -> Step:
        return next(step for step in self.plan.steps if step.label == label)


def _record_phases(store: GraphStore, plan: Plan) -> None:
    """Put a phase on record for ``--since last`` when every step of it is marked: from the
    moment its first step began, unless a later run of it is on record already."""
    marks = bootstrap_plan.marks(store)
    for phase in PHASES:
        labels = [s.label for s in plan.steps if s.label.startswith(f"{phase} ")]
        if not labels or any(label not in marks for label in labels):
            continue
        began = min(_began(marks[label]) for label in labels)
        mark = watermark.covered_until(store, phase)
        if mark is None or began > mark:
            since = plan.since if phase == "retrieve" else None
            watermark.advance(store, phase, began=began, since=since)
            logger.info("%s is on record since %s.", phase, began.isoformat())


def _began(mark: Any) -> dt.datetime:
    ended = dt.datetime.fromisoformat(mark.ended_at)
    return (ended - dt.timedelta(seconds=mark.seconds)).replace(microsecond=0)
