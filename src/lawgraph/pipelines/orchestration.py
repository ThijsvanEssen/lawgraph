"""The ``<phase> all`` commands: run every registered step of a phase in registry order."""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from lawgraph.config.settings import skip_step, skip_variable
from lawgraph.core.logging import get_logger, setup_logging
from lawgraph.core.time import parse_since
from lawgraph.db import ArangoStore
from lawgraph.pipelines import watermark
from lawgraph.pipelines.base import STOP
from lawgraph.pipelines.factory import add_since_argument, run_command
from lawgraph.sources.registry import SOURCES, RetrieveCtx, describe

logger = get_logger(__name__)

# One per server (lane): each server is paced on its own, so there is nothing to wait for.
DEFAULT_RETRIEVE_JOBS = len(
    {
        s.retrieve_lane or s.id
        for s in SOURCES
        if s.retrieve_main is not None and s.retrieve_argv_builder is not None
    }
)
DEFAULT_WINDOW = "730d"


@dataclass(frozen=True)
class _Step:
    source_id: str
    name: str
    main: Callable[..., None]
    argv: list[str]
    lane: str = ""
    after: tuple[str, ...] = ()  # source ids whose step must have ended first

    @property
    def lane_id(self) -> str:
        return self.lane or self.source_id


def _run_step(phase: str, step: _Step) -> str:
    """Run one step; ``ok``, ``failed`` or ``skipped``."""
    if skip_step(phase, step.source_id):
        logger.info("%s skipped (%s).", step.name, skip_variable(phase, step.source_id))
        return "skipped"
    label = f"{phase} {step.source_id.replace('_', '-')}"
    succeeded = run_command(
        step.name,
        step.main,
        step.argv,
        step=label,
        description=describe(phase, step.source_id),
    )
    return "ok" if succeeded else "failed"


def _run_in_lanes(phase: str, steps: list[_Step], jobs: int) -> list[tuple[str, str]]:
    """Run the lanes side by side, at most *jobs* steps at a time.

    The steps of one lane run one after the other. A step with ``after`` waits until those
    steps (of other lanes) have ended; it comes last in its own lane so the lane does not
    stand still, and while it waits it does not take one of the *jobs* places. Returns the
    results in the order of *steps*.
    """
    lanes: dict[str, list[_Step]] = {}
    for step in steps:
        lanes.setdefault(step.lane_id, []).append(step)
    ended = {step.source_id: threading.Event() for step in steps}
    places = threading.Semaphore(jobs)

    def run_lane(lane: list[_Step]) -> list[tuple[str, str]]:
        results = []
        waiting_last = sorted(lane, key=lambda s: bool(s.after))  # a stable sort
        for step in waiting_last:
            if STOP.is_set():
                break
            for source_id in step.after:
                if source_id in ended:
                    ended[source_id].wait()
            try:
                with places:
                    results.append((step.name, _run_step(phase, step)))
            finally:
                ended[step.source_id].set()
        return results

    with ThreadPoolExecutor(max_workers=len(lanes), thread_name_prefix=phase) as pool:
        futures = [pool.submit(run_lane, lane) for lane in lanes.values()]
        try:
            status = {name: state for f in futures for name, state in f.result()}
        except KeyboardInterrupt:
            # Ctrl-C reaches this thread only, and leaving the pool waits for the lanes.
            logger.warning(
                "Interrupted: the running steps store what they have and stop."
            )
            STOP.set()
            for event in ended.values():
                event.set()
            raise
    return [(step.name, status[step.name]) for step in steps]


def _run_phase(
    phase: str, steps: list[_Step], *, strict: bool = False, jobs: int = 1
) -> list[tuple[str, str]]:
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
    return results


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


_LAST_HELP = " 'last' goes on where the last complete run of this command began, however long ago."


def _run_marked(
    phase: str,
    args: argparse.Namespace,
    run: Callable[[], list[tuple[str, str]]],
    *,
    read_since: Callable[[argparse.Namespace], dt.datetime | None] = lambda a: a.since,
) -> None:
    """Resolve ``--since last``, run the phase and record that it is complete.

    *run* is called when ``args.since`` is a date; it exits when a step failed. A run with
    a skipped step is not complete. *read_since* says since when the run read its sources
    (None: all there is) when that is not ``--since``.
    """
    store = ArangoStore()
    if args.since == watermark.LAST:
        try:
            args.since = watermark.since_last(store, phase)
        except watermark.NothingOnRecord as exc:
            logger.error("%s", exc)
            sys.exit(2)
        logger.info(
            "%s all: since the last complete run (%s).",
            phase,
            args.since.isoformat(timespec="seconds"),
        )
    began = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    results = run()
    if all(state == "ok" for _, state in results):
        watermark.advance(store, phase, began=began, since=read_since(args))


def run_retrieve_all(argv: list[str] | None = None) -> None:
    setup_logging()
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

    _run_marked(
        "retrieve",
        args,
        lambda: _retrieve_all(args),
        # a full load reads what changed inside the window (all of it without one)
        read_since=lambda a: a.window if a.mode == "full" else a.since,
    )


def _retrieve_all(args: argparse.Namespace) -> list[tuple[str, str]]:
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
            s.retrieve_after,
        )
        for s in SOURCES
        if s.retrieve_main is not None and s.retrieve_argv_builder is not None
    ]
    return _run_phase("retrieve", steps, jobs=args.jobs)


def run_normalize_all(argv: list[str] | None = None) -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description="Run all normalize pipelines.")
    add_since_argument(
        parser,
        last=True,
        help="Only the raw records fetched since then (ISO date or 7d)." + _LAST_HELP,
    )
    args = parser.parse_args(argv)

    def run() -> list[tuple[str, str]]:
        steps = [
            _Step(s.id, s.display_name, s.normalize_main, _since_argv(args))
            for s in SOURCES
            if s.normalize_main is not None
        ]
        return _run_phase("normalize", steps)

    _run_marked("normalize", args, run)


def run_semantic_all(argv: list[str] | None = None) -> None:
    setup_logging()
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

    def run() -> list[tuple[str, str]]:
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
        return _run_phase("semantic", steps, strict=args.strict)

    _run_marked("semantic", args, run)
