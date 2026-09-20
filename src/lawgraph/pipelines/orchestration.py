"""The ``<phase> all`` commands: run every registered step of a phase in registry order."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass

from lawgraph.config.settings import skip_step, skip_variable
from lawgraph.core.logging import get_logger, setup_logging
from lawgraph.pipelines.factory import add_since_argument, run_command
from lawgraph.sources.registry import SOURCES, RetrieveCtx

logger = get_logger(__name__)


@dataclass(frozen=True)
class _Step:
    source_id: str
    name: str
    main: Callable[..., None]
    argv: list[str]


def _run_phase(phase: str, steps: list[_Step], *, strict: bool = False) -> None:
    """Run *steps*, log a summary table and exit 1 when any step failed."""
    label = f"{phase} all"
    results: list[tuple[str, str]] = []
    for step in steps:
        if skip_step(phase, step.source_id):
            logger.info(
                "%s skipped (%s).", step.name, skip_variable(phase, step.source_id)
            )
            results.append((step.name, "skipped"))
            continue
        succeeded = run_command(step.name, step.main, step.argv)
        results.append((step.name, "ok" if succeeded else "failed"))
        if strict and not succeeded:
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


def _since_argv(args: argparse.Namespace) -> list[str]:
    return ["--since", args.since.isoformat()] if args.since else []


def run_retrieve_all(argv: list[str] | None = None) -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description="Run all retrieve pipelines.")
    add_since_argument(parser, default="1d")
    parser.add_argument(
        "--mode", choices=["incremental", "full"], default="incremental"
    )
    args = parser.parse_args(argv)

    ctx = RetrieveCtx(since=args.since.isoformat(), mode=args.mode)
    steps = [
        _Step(s.id, s.display_name, s.retrieve_main, s.retrieve_argv_builder(ctx))
        for s in SOURCES
        if s.retrieve_main is not None and s.retrieve_argv_builder is not None
    ]
    _run_phase("retrieve", steps)


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
