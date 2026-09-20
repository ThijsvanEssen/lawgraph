"""Shared command-line plumbing of the pipeline steps.

``run_step`` is the one place that decides how a step ends: it logs the result and exits
with code 1 when the step raised or its result has errors. ``make_pipeline_cli`` builds the
``main(argv)`` of a normalize or semantic pipeline on top of it. ``run_command`` is how a
composite command (``<phase> all``, ``bootstrap``, ``expand-graph``) runs another command.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections.abc import Callable
from typing import Any

from lawgraph.core.logging import get_logger, setup_logging
from lawgraph.core.models import PipelineResult
from lawgraph.core.time import parse_since
from lawgraph.db import ArangoStore

logger = get_logger(__name__)

_SINCE_HELP = (
    "Only records since this moment: ISO 8601 ('2024-01-01') or relative ('7d')."
)


def add_since_argument(
    parser: argparse.ArgumentParser,
    flag: str = "--since",
    *,
    default: str | None = None,
    help: str = _SINCE_HELP,
) -> None:
    parser.add_argument(flag, type=_since, default=_since(default), help=help)


def _since(value: str | None) -> dt.datetime | None:
    try:
        return parse_since(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def run_step(name: str, run: Callable[[], PipelineResult]) -> None:
    """Run one pipeline step, log its summary, and exit 1 when it failed."""
    setup_logging()
    try:
        result = run()
    except Exception as exc:
        logger.error("%s failed: %s", name, exc)
        sys.exit(1)

    logger.info("%s: %s.", name, result.summary())
    for error in result.errors:
        logger.error("%s error: %s", name, error)
    if result.errors:
        sys.exit(1)


def run_command(name: str, main: Callable[..., None], argv: list[str]) -> bool:
    """Run ``main(argv)``; return False when it raised or exited with a non-zero code."""
    logger.info("%s: starting.", name)
    try:
        main(argv=argv)
    except SystemExit as exc:
        if exc.code not in (None, 0):
            logger.error("%s: exited with code %s.", name, exc.code)
            return False
    except Exception as exc:
        logger.error("%s: raised %s", name, exc)
        return False
    logger.info("%s: completed.", name)
    return True


def make_pipeline_cli(
    pipeline_cls: type,
    *,
    description: str,
    with_since: bool = False,
    add_args: Callable[[argparse.ArgumentParser], None] | None = None,
    make_extra_kwargs: Callable[[argparse.Namespace], dict[str, Any]] | None = None,
) -> Callable[[list[str] | None], None]:
    """Build ``main(argv)`` for a pipeline whose ``run`` takes at most ``since``.

    ``add_args`` adds options to the parser; ``make_extra_kwargs`` turns the parsed options
    into constructor arguments of *pipeline_cls*.
    """

    def main(argv: list[str] | None = None) -> None:
        parser = argparse.ArgumentParser(description=description)
        if with_since:
            add_since_argument(parser)
        if add_args:
            add_args(parser)
        args = parser.parse_args(argv)

        def run() -> PipelineResult:
            extra = make_extra_kwargs(args) if make_extra_kwargs else {}
            pipeline = pipeline_cls(store=ArangoStore(), **extra)
            return pipeline.run(since=args.since) if with_since else pipeline.run()

        run_step(pipeline_cls.__name__, run)

    return main
