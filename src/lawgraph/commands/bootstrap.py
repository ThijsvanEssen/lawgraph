"""``lawgraph bootstrap``: fill an empty database, as planned in ``commands/bootstrap_plan.py``.

The retrieves run in a lane per server and every step that writes the graph in one write
lane, one at a time (``pipelines/lanes.py``); each lane takes the first of its steps whose
wait is over, so a normalize runs as soon as what it reads is there (``normalize tk`` while
Rechtspraak is still being retrieved). The producing sources (Tweede Kamer, Rechtspraak,
Staatscourant, Eerste Kamer, ECHR) load a window (``--window``, default 730d; ``all`` loads
their whole history), the reference sources load in full, ``--jobs`` retrieves at most that
many sources at once.

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
from typing import Any

from lawgraph.commands import bootstrap_plan
from lawgraph.commands.bootstrap_plan import WRITE_LANE, Code, Plan
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.db import GraphStore
from lawgraph.pipelines import watermark
from lawgraph.pipelines.command import Outcome, combined_result, command_parser
from lawgraph.pipelines.lanes import Step, run_steps
from lawgraph.pipelines.orchestration import (
    DEFAULT_RETRIEVE_JOBS,
    DEFAULT_WINDOW,
    window_since,
)
from lawgraph.sources.addresses import PHASES

logger = get_logger(__name__)


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
        if (args.skip_retrieve and step.phase == "retrieve")
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
    outcomes = run_plan(plan, store, code, done | counted, args.jobs, args.strict)
    _record_phases(store, plan)
    return combined_result(outcomes)


def _parser() -> argparse.ArgumentParser:
    parser = command_parser(description="Fill an empty LawGraph database.")
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


def run_plan(
    plan: Plan, store: GraphStore, code: Code, done: set[str], jobs: int, strict: bool
) -> list[Outcome]:
    """The steps of *plan* not *done*, in their lanes; each that ends ``ok`` is marked."""

    def mark(step: Step, outcome: Outcome) -> None:
        bootstrap_plan.mark_done(store, step.label, outcome.seconds, code)

    return run_steps(
        plan.steps,
        jobs=jobs,
        strict=strict,
        write_lane=WRITE_LANE,
        done=done,
        on_ok=mark,
    )


def _record_phases(store: GraphStore, plan: Plan) -> None:
    """Put a phase on record for ``--since last`` when every step of it is marked: from the
    moment its first step began, unless a later run of it is on record already."""
    marks = bootstrap_plan.marks(store)
    for phase in PHASES:
        labels = [s.label for s in plan.steps if s.phase == phase]
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
