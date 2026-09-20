"""The ``<phase> all`` commands: run every registered step of a phase in registry order."""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from lawgraph.config.settings import skip_step, skip_variable
from lawgraph.core.logging import get_logger, setup_logging
from lawgraph.core.time import parse_since
from lawgraph.db import ArangoStore
from lawgraph.pipelines.factory import add_since_argument, run_command
from lawgraph.sources.registry import SOURCES, RetrieveCtx

logger = get_logger(__name__)

DEFAULT_RETRIEVE_JOBS = 4
DEFAULT_WINDOW = "730d"


@dataclass(frozen=True)
class _Step:
    source_id: str
    name: str
    main: Callable[..., None]
    argv: list[str]
    lane: str = ""

    @property
    def lane_id(self) -> str:
        return self.lane or self.source_id


def _run_step(phase: str, step: _Step) -> str:
    """Run one step; ``ok``, ``failed`` or ``skipped``."""
    if skip_step(phase, step.source_id):
        logger.info("%s skipped (%s).", step.name, skip_variable(phase, step.source_id))
        return "skipped"
    return "ok" if run_command(step.name, step.main, step.argv) else "failed"


def _run_lane(phase: str, steps: list[_Step]) -> list[tuple[str, str]]:
    return [(step.name, _run_step(phase, step)) for step in steps]


def _run_in_lanes(phase: str, steps: list[_Step], jobs: int) -> list[tuple[str, str]]:
    """Run the lanes on *jobs* threads; the steps of one lane run one after the other.

    Returns the results in the order of *steps*.
    """
    lanes: dict[str, list[_Step]] = {}
    for step in steps:
        lanes.setdefault(step.lane_id, []).append(step)
    with ThreadPoolExecutor(max_workers=jobs, thread_name_prefix=phase) as pool:
        futures = [pool.submit(_run_lane, phase, lane) for lane in lanes.values()]
        status = {name: state for f in futures for name, state in f.result()}
    return [(step.name, status[step.name]) for step in steps]


def _run_phase(
    phase: str, steps: list[_Step], *, strict: bool = False, jobs: int = 1
) -> None:
    """Run *steps*, log a summary table and exit 1 when any step failed.

    With ``jobs > 1`` the steps run in lanes (see ``run_retrieve_all``); ``strict`` only
    applies to a sequential run.
    """
    label = f"{phase} all"
    results: list[tuple[str, str]] = []
    if jobs > 1:
        results = _run_in_lanes(phase, steps, jobs)
    else:
        for step in steps:
            state = _run_step(phase, step)
            results.append((step.name, state))
            if strict and state == "failed":
                logger.error("%s: aborting after '%s' (--strict).", label, step.name)
                break

    logger.info("%s summary:", label)
    for name, status in results:
        logger.info("  %-40s %s", name, status)
    failures = [name for name, status in results if status == "failed"]
    if failures:
        logger.error("%s finished with %d failure(s).", label, len(failures))
        sys.exit(1)
    logger.info("%s completed successfully.", label)


def _window(value: str) -> dt.datetime | None:
    """A ``--window``: a date like ``--since``, or ``all`` for no window at all."""
    if value.strip().lower() == "all":
        return None
    try:
        return parse_since(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _since_argv(args: argparse.Namespace) -> list[str]:
    return ["--since", args.since.isoformat()] if args.since else []


def run_retrieve_all(argv: list[str] | None = None) -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description="Run all retrieve pipelines.")
    add_since_argument(parser, default="1d")
    parser.add_argument(
        "--mode", choices=["incremental", "full"], default="incremental"
    )
    parser.add_argument(
        "--window",
        type=_window,
        default=_window(DEFAULT_WINDOW),
        metavar="DATE",
        help="Full mode: the sources that keep producing (Tweede Kamer, "
        "Staatscourant, Eerste Kamer, ECHR) read only what changed since then. "
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

    ctx = RetrieveCtx(
        since=args.since.isoformat(),
        mode=args.mode,
        window=args.window.isoformat() if args.window else None,
    )
    steps = [
        _Step(
            s.id,
            s.display_name,
            s.retrieve_main,
            s.retrieve_argv_builder(ctx),
            s.retrieve_lane or "",
        )
        for s in SOURCES
        if s.retrieve_main is not None and s.retrieve_argv_builder is not None
    ]
    if args.jobs > 1:
        # Create the database and schema once; threads that all find it missing would race.
        ArangoStore()
    _run_phase("retrieve", steps, jobs=args.jobs)


def run_normalize_all(argv: list[str] | None = None) -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description="Run all normalize pipelines.")
    add_since_argument(parser)
    args = parser.parse_args(argv)

    steps = [
        _Step(s.id, s.display_name, s.normalize_main, _since_argv(args))
        for s in SOURCES
        if s.normalize_main is not None
    ]
    _run_phase("normalize", steps)


def run_semantic_all(argv: list[str] | None = None) -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description="Run all semantic pipelines.")
    add_since_argument(
        parser,
        help="Passed to the pipelines that accept --since; the others run in full.",
    )
    parser.add_argument(
        "--strict", action="store_true", help="Stop at the first failing step."
    )
    args = parser.parse_args(argv)

    steps = [
        _Step(
            s.id,
            s.display_name,
            s.semantic_main,
            _since_argv(args) if s.semantic_accepts_since else [],
        )
        for s in SOURCES
        if s.semantic_main is not None
    ]
    _run_phase("semantic", steps, strict=args.strict)
