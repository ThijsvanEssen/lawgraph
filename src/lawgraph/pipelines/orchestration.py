"""The ``<phase> all`` commands: every pipeline of a phase, in registry order.

``run_pipelines`` runs pipelines of the registry as steps (``lanes.run_steps``: side by side
in lanes for retrieve, with a line as each ends and the table of how each ended), and
``_run_phase`` all pipelines of a phase, keeping the mark of ``--since last``. The three
commands at the end are what ``lawgraph <phase> all`` runs.
"""

from __future__ import annotations

import argparse
import datetime as dt
from collections.abc import Callable

from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.core.time import parse_since
from lawgraph.db import GraphStore
from lawgraph.pipelines import watermark
from lawgraph.pipelines.command import (
    Outcome,
    State,
    add_since_argument,
    combined_result,
    command_parser,
)
from lawgraph.pipelines.lanes import Step, run_steps
from lawgraph.pipelines.retrieve_commands import RetrieveMode, add_mode_argument
from lawgraph.sources.registry import PIPELINES, Phase, Pipeline, RetrieveCtx

logger = get_logger(__name__)

# One per server (lane): each server is paced on its own, so there is nothing to wait for.
DEFAULT_RETRIEVE_JOBS = len({p.lane_id for p in PIPELINES["retrieve"]})
DEFAULT_WINDOW = "730d"


ArgvOf = Callable[[Pipeline], list[str]]  # the options a pipeline gets in this run

IN_TURN = "in turn"  # the one lane of a run with one job


def run_pipelines(
    pipelines: list[Pipeline],
    argv_of: ArgvOf,
    *,
    strict: bool = False,
    jobs: int = 1,
) -> list[Outcome]:
    """Run *pipelines*, each with the options *argv_of* gives it, and log how each ended.

    With ``jobs > 1`` they run in a lane per server, each lane in registry order with those
    that wait for another last (``lanes.run_steps``); with one job one after the other, in
    registry order. ``strict`` starts none after the first that failed.
    """
    steps = [
        Step(
            p.address,
            p.lane_id if jobs > 1 else IN_TURN,
            p.command,
            tuple(argv_of(p)),
            tuple(f"{p.phase} {a}" for a in p.after) if jobs > 1 else (),
            p.description,
        )
        for p in pipelines
    ]
    return run_steps(steps, jobs=jobs, in_order=True, strict=strict)


def window_since(value: str) -> dt.datetime | None:
    """A ``--window``: a date like ``--since``, or ``all`` for no window at all."""
    if value.strip().lower() == "all":
        return None
    try:
        return parse_since(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _since_argv(args: argparse.Namespace) -> ArgvOf:
    """``--since`` for a pipeline whose command has it; one without it runs in full."""
    since = ["--since", args.since.isoformat()] if args.since else []
    return lambda pipeline: since if pipeline.command.accepts_since else []


_LAST_HELP = " 'last' goes on where the last complete run of this command began, however long ago."


def _run_phase(
    phase: Phase,
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    argv_of: Callable[[argparse.Namespace], ArgvOf],
    *,
    read_since: Callable[[argparse.Namespace], dt.datetime | None] = lambda a: a.since,
    strict: bool = False,
    jobs: int = 1,
) -> PipelineResult:
    """Resolve ``--since last``, run the phase and record when it was complete.

    Complete is: every pipeline ended ``ok`` (a skipped one is a hole). *read_since* says
    since when the run read its sources (None: all there is) when that is not ``--since``.
    The store is opened before any lane starts, which also creates the schema once.
    """
    store = GraphStore()
    if args.since == watermark.LAST:
        try:
            args.since = watermark.since_last(store, phase)
        except watermark.NothingOnRecord as exc:
            parser.error(str(exc))  # a wrong command line: exit code 2
        logger.info(
            "Since the last complete run (%s).",
            args.since.isoformat(timespec="seconds"),
        )
    began = dt.datetime.now(dt.UTC).replace(microsecond=0)
    outcomes = run_pipelines(
        _pipelines_of(phase, args), argv_of(args), strict=strict, jobs=jobs
    )
    if phase != "retrieve":
        # what normalize and semantic wrote, known to the planner before the API reads it
        store.vacuum_analyze()
    # says nothing about a date
    filling_gaps = getattr(args, "mode", None) is RetrieveMode.GAPS
    if not filling_gaps and all(outcome.state is State.OK for outcome in outcomes):
        watermark.advance(store, phase, began=began, since=read_since(args))
    return combined_result(outcomes)


def retrieve_all(argv: list[str] | None = None) -> PipelineResult:
    parser = command_parser(description="Run all retrieve pipelines.")
    add_since_argument(
        parser,
        default="1d",
        last=True,
        help="Incremental mode: what changed since then (ISO date, 7d, 2h or 90m)."
        + _LAST_HELP,
    )
    add_mode_argument(
        parser,
        (RetrieveMode.INCREMENTAL, RetrieveMode.FULL, RetrieveMode.GAPS),
        default=RetrieveMode.INCREMENTAL,
        help="incremental: what changed since --since; full: all inside --window; gaps: what "
        "the graph refers to and only holds a stub of, from every source that can fetch it.",
    )
    parser.add_argument(
        "--window",
        type=window_since,
        default=window_since(DEFAULT_WINDOW),
        metavar="DATE",
        help="Full mode: the sources that keep producing (Tweede Kamer, Rechtspraak, "
        "Staatscourant, Eerste Kamer, ECHR, the implementing measures of EUR-Lex) read only "
        "what changed since then. ISO date, relative (730d) or 'all' for the whole history. "
        f"Default: {DEFAULT_WINDOW}. The reference sources (BWB, Verdragenbank) are read in "
        "full; the sources that choose from the graph (tk-content, eurlex) or from a stored "
        "list run as they always do.",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=DEFAULT_RETRIEVE_JOBS,
        metavar="N",
        help="Sources to retrieve at the same time; sources on one server always run "
        "one after the other. 1 runs them all in turn. Default: %(default)s.",
    )
    args = parser.parse_args(argv)
    if args.jobs < 1:
        parser.error("--jobs must be at least 1")

    return _run_phase(
        "retrieve",
        parser,
        args,
        _retrieve_argv,
        # a full load reads what changed inside the window (all of it without one)
        read_since=lambda a: a.window if a.mode is RetrieveMode.FULL else a.since,
        jobs=args.jobs,
    )


def _pipelines_of(phase: Phase, args: argparse.Namespace) -> list[Pipeline]:
    """The pipelines ``<phase> all`` runs: all of them, but in gaps mode those that can fill
    gaps."""
    if phase == "retrieve" and args.mode is RetrieveMode.GAPS:
        return [pipeline for pipeline in PIPELINES[phase] if pipeline.fills_gaps]
    return PIPELINES[phase]


def _retrieve_argv(args: argparse.Namespace) -> ArgvOf:
    if args.mode is RetrieveMode.GAPS:
        return lambda pipeline: ["--mode", RetrieveMode.GAPS]
    ctx = RetrieveCtx(
        since=args.since.isoformat(),
        mode=args.mode,
        window=args.window.isoformat() if args.window else None,
    )
    return lambda pipeline: pipeline.argv_for_all(ctx) if pipeline.argv_for_all else []


def normalize_all(argv: list[str] | None = None) -> PipelineResult:
    parser = command_parser(description="Run all normalize pipelines.")
    add_since_argument(
        parser,
        last=True,
        help="Only the raw records fetched since then (ISO date, 7d, 2h or 90m)."
        + _LAST_HELP,
    )
    args = parser.parse_args(argv)
    return _run_phase("normalize", parser, args, _since_argv)


def semantic_all(argv: list[str] | None = None) -> PipelineResult:
    parser = command_parser(description="Run all semantic pipelines.")
    add_since_argument(
        parser,
        last=True,
        help="Passed to the pipelines that accept --since; the others run in full."
        + _LAST_HELP,
    )
    parser.add_argument(
        "--strict", action="store_true", help="Stop at the first failing step."
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print the names of the steps in the order they run, one a line, and run "
        "none: what scripts/weekly.sh takes one by one.",
    )
    args = parser.parse_args(argv)
    if args.list:
        for pipeline in PIPELINES["semantic"]:
            print(pipeline.name)
        return PipelineResult()
    return _run_phase("semantic", parser, args, _since_argv, strict=args.strict)
