"""The ``<phase> all`` commands: every pipeline of a phase, in registry order.

``run_pipeline`` runs one pipeline of the registry through ``command.run_command``,
``run_pipelines`` a list of them (side by side in lanes for retrieve) with the table of how
each ended, and ``_run_phase`` all pipelines of a phase, keeping the mark of ``--since
last``. The three commands at the end are what ``lawgraph <phase> all`` runs.
"""

from __future__ import annotations

import argparse
import datetime as dt
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from lawgraph.config.settings import skip_step, skip_variable
from lawgraph.core.logging import get_logger, log_step
from lawgraph.core.models import PipelineResult
from lawgraph.core.time import format_duration, parse_since
from lawgraph.db import ArangoStore
from lawgraph.pipelines import watermark
from lawgraph.pipelines.base import STOP
from lawgraph.pipelines.command import (
    Outcome,
    State,
    accepts_since,
    add_since_argument,
    combined_result,
    run_command,
)
from lawgraph.pipelines.retrieve_commands import GAPS
from lawgraph.sources.registry import PIPELINES, Phase, Pipeline, RetrieveCtx

logger = get_logger(__name__)

# One per server (lane): each server is paced on its own, so there is nothing to wait for.
DEFAULT_RETRIEVE_JOBS = len(
    {p.lane_id for p in PIPELINES["retrieve"] if p.argv_for_all is not None}
)
DEFAULT_WINDOW = "730d"


def run_pipeline(pipeline: Pipeline, argv: list[str]) -> Outcome:
    """Run *pipeline*, unless ``LAWGRAPH_<PHASE>_SKIP_<NAME>`` leaves it out."""
    if skip_step(pipeline.phase, pipeline.name):
        with log_step(pipeline.address):
            logger.info("Skipped (%s).", skip_variable(pipeline.phase, pipeline.name))
        return Outcome(pipeline.address, State.SKIPPED)
    return run_command(
        pipeline.address, pipeline.command, argv, description=pipeline.description
    )


ArgvOf = Callable[[Pipeline], list[str]]  # the options a pipeline gets in this run


def _run_pipelines_in_lanes(
    pipelines: list[Pipeline], argv_of: ArgvOf, jobs: int
) -> list[Outcome]:
    """Run the lanes side by side, at most *jobs* pipelines at a time.

    The pipelines of one lane run one after the other. One with ``after`` waits until those
    pipelines (of other lanes) have ended; it comes last in its own lane so the lane does
    not stand still, and while it waits it does not take one of the *jobs* places. Returns
    the outcomes in the order of *pipelines*.
    """
    lanes: dict[str, list[Pipeline]] = {}
    for pipeline in pipelines:
        lanes.setdefault(pipeline.lane_id, []).append(pipeline)
    ended = {pipeline.name: threading.Event() for pipeline in pipelines}
    places = threading.Semaphore(jobs)

    def run_lane(lane: list[Pipeline]) -> list[Outcome]:
        outcomes = []
        waiting_last = sorted(lane, key=lambda p: bool(p.after))  # a stable sort
        for pipeline in waiting_last:
            if STOP.is_set():
                break
            for name in pipeline.after:
                if name in ended:
                    ended[name].wait()
            try:
                with places:
                    outcomes.append(run_pipeline(pipeline, argv_of(pipeline)))
            finally:
                ended[pipeline.name].set()
        return outcomes

    with ThreadPoolExecutor(max_workers=len(lanes), thread_name_prefix="lane") as pool:
        futures = [pool.submit(run_lane, lane) for lane in lanes.values()]
        try:
            by_label = {o.label: o for future in futures for o in future.result()}
        except KeyboardInterrupt:
            # Ctrl-C reaches this thread only, and leaving the pool waits for the lanes.
            logger.warning(
                "Interrupted: the running pipelines store what they have and stop."
            )
            STOP.set()
            for event in ended.values():
                event.set()
            raise
    return [by_label[pipeline.address] for pipeline in pipelines]


def run_pipelines(
    pipelines: list[Pipeline],
    argv_of: ArgvOf,
    *,
    strict: bool = False,
    jobs: int = 1,
) -> list[Outcome]:
    """Run *pipelines*, each with the options *argv_of* gives it, and log how each ended.

    With ``jobs > 1`` they run in lanes; ``strict`` (stop at the first that failed) only
    applies to a run in turn.
    """
    if jobs > 1:
        outcomes = _run_pipelines_in_lanes(pipelines, argv_of, jobs)
    else:
        outcomes = []
        for pipeline in pipelines:
            outcomes.append(run_pipeline(pipeline, argv_of(pipeline)))
            if strict and outcomes[-1].state is State.FAILED:
                logger.error("Stopping after '%s' (--strict).", pipeline.address)
                break

    for outcome in outcomes:
        took = (
            format_duration(outcome.seconds)
            if outcome.state is not State.SKIPPED
            else ""
        )
        logger.info("  %-32s %8s  %s", outcome.label, took, outcome.state.value)
    return outcomes


def _window(value: str) -> dt.datetime | None:
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
    return lambda pipeline: since if accepts_since(pipeline.command) else []


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
    store = ArangoStore()
    if args.since == watermark.LAST:
        try:
            args.since = watermark.since_last(store, phase)
        except watermark.NothingOnRecord as exc:
            parser.error(str(exc))  # a wrong command line: exit code 2
        logger.info(
            "Since the last complete run (%s).",
            args.since.isoformat(timespec="seconds"),
        )
    began = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    outcomes = run_pipelines(
        _pipelines_of(phase, args), argv_of(args), strict=strict, jobs=jobs
    )
    filling_gaps = getattr(args, "mode", None) == GAPS  # says nothing about a date
    if not filling_gaps and all(outcome.state is State.OK for outcome in outcomes):
        watermark.advance(store, phase, began=began, since=read_since(args))
    return combined_result(outcomes)


def retrieve_all(argv: list[str] | None = None) -> PipelineResult:
    parser = argparse.ArgumentParser(description="Run all retrieve pipelines.")
    add_since_argument(
        parser,
        default="1d",
        last=True,
        help="Incremental mode: what changed since then (ISO date or 7d)." + _LAST_HELP,
    )
    parser.add_argument(
        "--mode",
        choices=["incremental", "full", GAPS],
        default="incremental",
        help="incremental: what changed since --since; full: all inside --window; gaps: what "
        "the graph refers to and only holds a stub of, from every source that can fetch it.",
    )
    parser.add_argument(
        "--window",
        type=_window,
        default=_window(DEFAULT_WINDOW),
        metavar="DATE",
        help="Full mode: the sources that keep producing (Tweede Kamer, "
        "Rechtspraak, Staatscourant, Eerste Kamer, ECHR) read only what changed since then. "
        "ISO date, relative (730d) or 'all' for the whole history. Default: "
        f"{DEFAULT_WINDOW}. Reference sources (BWB, Verdragenbank) are always read in full.",
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
        read_since=lambda a: a.window if a.mode == "full" else a.since,
        jobs=args.jobs,
    )


def _pipelines_of(phase: Phase, args: argparse.Namespace) -> list[Pipeline]:
    """The pipelines ``<phase> all`` runs: all of them, but for retrieve those that have
    options for it, or in gaps mode those that can fill gaps."""
    if phase != "retrieve":
        return PIPELINES[phase]
    if args.mode == GAPS:
        return [pipeline for pipeline in PIPELINES[phase] if pipeline.fills_gaps]
    return [p for p in PIPELINES[phase] if p.argv_for_all is not None]


def _retrieve_argv(args: argparse.Namespace) -> ArgvOf:
    if args.mode == GAPS:
        return lambda pipeline: ["--mode", GAPS]
    ctx = RetrieveCtx(
        since=args.since.isoformat(),
        mode=args.mode,
        window=args.window.isoformat() if args.window else None,
    )
    return lambda pipeline: pipeline.argv_for_all(ctx) if pipeline.argv_for_all else []


def normalize_all(argv: list[str] | None = None) -> PipelineResult:
    parser = argparse.ArgumentParser(description="Run all normalize pipelines.")
    add_since_argument(
        parser,
        last=True,
        help="Only the raw records fetched since then (ISO date or 7d)." + _LAST_HELP,
    )
    args = parser.parse_args(argv)
    return _run_phase("normalize", parser, args, _since_argv)


def semantic_all(argv: list[str] | None = None) -> PipelineResult:
    parser = argparse.ArgumentParser(description="Run all semantic pipelines.")
    add_since_argument(
        parser,
        last=True,
        help="Passed to the pipelines that accept --since; the others run in full."
        + _LAST_HELP,
    )
    parser.add_argument(
        "--strict", action="store_true", help="Stop at the first failing step."
    )
    args = parser.parse_args(argv)
    return _run_phase("semantic", parser, args, _since_argv, strict=args.strict)
