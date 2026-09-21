"""The ``<phase> all`` commands: every registered step of a phase, in registry order.

A step is one phase of one source, and its label is what one types: ``normalize bwb``.
``run_phase`` runs the steps through ``execution.execute`` (side by side in lanes for
retrieve), logs the table of how each ended and hands the outcomes back; the commands
below turn them into their own result and keep the mark of ``--since last``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from lawgraph.config.settings import skip_step, skip_variable
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.core.time import format_duration, parse_since
from lawgraph.db import ArangoStore
from lawgraph.pipelines import watermark
from lawgraph.pipelines.base import STOP
from lawgraph.pipelines.command import Command, accepts_since, add_since_argument
from lawgraph.pipelines.execution import Outcome, State, combined, execute, skipped
from lawgraph.sources.registry import SOURCES, RetrieveCtx, describe

logger = get_logger(__name__)

# One per server (lane): each server is paced on its own, so there is nothing to wait for.
DEFAULT_RETRIEVE_JOBS = len(
    {
        s.retrieve_lane or s.id
        for s in SOURCES
        if s.retrieve_command is not None and s.retrieve_argv_builder is not None
    }
)
DEFAULT_WINDOW = "730d"


@dataclass(frozen=True)
class Step:
    """One phase of one source, ready to run."""

    phase: str
    source_id: str
    command: Command
    argv: list[str]
    lane: str = ""  # steps of one lane (one server) never run at the same time
    after: tuple[str, ...] = ()  # source ids whose step must have ended first

    @property
    def label(self) -> str:
        """``normalize tk-dossiers``: the words of the command line."""
        return f"{self.phase} {self.source_id.replace('_', '-')}"

    @property
    def lane_id(self) -> str:
        return self.lane or self.source_id


def _run(step: Step) -> Outcome:
    if skip_step(step.phase, step.source_id):
        return skipped(step.label, skip_variable(step.phase, step.source_id))
    return execute(
        step.label,
        step.command,
        step.argv,
        description=describe(step.phase, step.source_id),
    )


def _run_in_lanes(steps: list[Step], jobs: int) -> list[Outcome]:
    """Run the lanes side by side, at most *jobs* steps at a time.

    The steps of one lane run one after the other. A step with ``after`` waits until those
    steps (of other lanes) have ended; it comes last in its own lane so the lane does not
    stand still, and while it waits it does not take one of the *jobs* places. Returns the
    outcomes in the order of *steps*.
    """
    lanes: dict[str, list[Step]] = {}
    for step in steps:
        lanes.setdefault(step.lane_id, []).append(step)
    ended = {step.source_id: threading.Event() for step in steps}
    places = threading.Semaphore(jobs)

    def run_lane(lane: list[Step]) -> list[Outcome]:
        outcomes = []
        waiting_last = sorted(lane, key=lambda s: bool(s.after))  # a stable sort
        for step in waiting_last:
            if STOP.is_set():
                break
            for source_id in step.after:
                if source_id in ended:
                    ended[source_id].wait()
            try:
                with places:
                    outcomes.append(_run(step))
            finally:
                ended[step.source_id].set()
        return outcomes

    with ThreadPoolExecutor(max_workers=len(lanes), thread_name_prefix="lane") as pool:
        futures = [pool.submit(run_lane, lane) for lane in lanes.values()]
        try:
            by_label = {o.label: o for future in futures for o in future.result()}
        except KeyboardInterrupt:
            # Ctrl-C reaches this thread only, and leaving the pool waits for the lanes.
            logger.warning(
                "Interrupted: the running steps store what they have and stop."
            )
            STOP.set()
            for event in ended.values():
                event.set()
            raise
    return [by_label[step.label] for step in steps]


def run_phase(
    steps: list[Step], *, strict: bool = False, jobs: int = 1
) -> list[Outcome]:
    """Run *steps* and log the table of how each ended.

    With ``jobs > 1`` the steps run in lanes; ``strict`` (stop at the first failed step)
    only applies to a run in turn.
    """
    if jobs > 1:
        outcomes = _run_in_lanes(steps, jobs)
    else:
        outcomes = []
        for step in steps:
            outcomes.append(_run(step))
            if strict and outcomes[-1].state is State.FAILED:
                logger.error("Stopping after '%s' (--strict).", step.label)
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


def _since_argv(args: argparse.Namespace, command: Command) -> list[str]:
    """``--since`` for a command that has it; a command without it runs in full."""
    if args.since and accepts_since(command):
        return ["--since", args.since.isoformat()]
    return []


_LAST_HELP = " 'last' goes on where the last complete run of this command began, however long ago."


def _run_and_mark(
    phase: str,
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    steps_of: Callable[[argparse.Namespace], list[Step]],
    *,
    read_since: Callable[[argparse.Namespace], dt.datetime | None] = lambda a: a.since,
    strict: bool = False,
    jobs: int = 1,
) -> PipelineResult:
    """Resolve ``--since last``, run the phase and record when it was complete.

    Complete is: every step ended ``ok`` (a skipped step is a hole). *read_since* says
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
    outcomes = run_phase(steps_of(args), strict=strict, jobs=jobs)
    if all(outcome.state is State.OK for outcome in outcomes):
        watermark.advance(store, phase, began=began, since=read_since(args))
    return combined(outcomes)


def retrieve_all(argv: list[str] | None = None) -> PipelineResult:
    parser = argparse.ArgumentParser(description="Run all retrieve pipelines.")
    add_since_argument(
        parser,
        default="1d",
        last=True,
        help="Incremental mode: what changed since then (ISO date or 7d)." + _LAST_HELP,
    )
    parser.add_argument(
        "--mode", choices=["incremental", "full"], default="incremental"
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

    return _run_and_mark(
        "retrieve",
        parser,
        args,
        _retrieve_steps,
        # a full load reads what changed inside the window (all of it without one)
        read_since=lambda a: a.window if a.mode == "full" else a.since,
        jobs=args.jobs,
    )


def _retrieve_steps(args: argparse.Namespace) -> list[Step]:
    ctx = RetrieveCtx(
        since=args.since.isoformat(),
        mode=args.mode,
        window=args.window.isoformat() if args.window else None,
    )
    return [
        Step(
            "retrieve",
            s.id,
            s.retrieve_command,
            s.retrieve_argv_builder(ctx),
            s.retrieve_lane or "",
            s.retrieve_after,
        )
        for s in SOURCES
        if s.retrieve_command is not None and s.retrieve_argv_builder is not None
    ]


def normalize_all(argv: list[str] | None = None) -> PipelineResult:
    parser = argparse.ArgumentParser(description="Run all normalize pipelines.")
    add_since_argument(
        parser,
        last=True,
        help="Only the raw records fetched since then (ISO date or 7d)." + _LAST_HELP,
    )
    args = parser.parse_args(argv)
    return _run_and_mark("normalize", parser, args, _normalize_steps)


def _normalize_steps(args: argparse.Namespace) -> list[Step]:
    return [
        Step(
            "normalize",
            s.id,
            s.normalize_command,
            _since_argv(args, s.normalize_command),
        )
        for s in SOURCES
        if s.normalize_command is not None
    ]


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
    return _run_and_mark("semantic", parser, args, _semantic_steps, strict=args.strict)


def _semantic_steps(args: argparse.Namespace) -> list[Step]:
    return [
        Step(
            "semantic", s.id, s.semantic_command, _since_argv(args, s.semantic_command)
        )
        for s in SOURCES
        if s.semantic_command is not None
    ]
