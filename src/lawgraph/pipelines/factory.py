"""Factory for generating pipeline CLI entry points.

Every normalize and semantic CLI follows the same boilerplate pattern.
``make_pipeline_cli`` generates a ``main(argv)`` function that handles:
  - argument parsing (--since, --since-days)
  - load_dotenv / setup_logging
  - ArangoStore construction
  - pipeline instantiation and run()
  - error logging and sys.exit(1) on failure

Usage (typical normalize CLI):
    from lawgraph.pipelines.factory import make_pipeline_cli
    from lawgraph.pipelines.normalize.bwb import BWBNormalizePipeline
    main = make_pipeline_cli(BWBNormalizePipeline, description="...", with_since=True)

For pipelines with extra constructor args, supply ``add_args`` and ``make_extra_kwargs``:
    def _add(parser):
        parser.add_argument("--store-citations", action="store_true")
    def _kwargs(args):
        return {"store_citations": args.store_citations}
    main = make_pipeline_cli(MyPipeline, add_args=_add, make_extra_kwargs=_kwargs)
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from typing import Any, Callable

from dotenv import load_dotenv

from lawgraph.core.logging import get_logger, setup_logging
from lawgraph.core.time import parse_since as _parse_since
from lawgraph.db import ArangoStore

_SINCE_HELP = "Only process records fetched since this date (ISO 8601 or '7d')."
_SINCE_DAYS_HELP = "Look back this many days; 0 means full history."


def make_pipeline_cli(
    pipeline_cls: type,
    *,
    description: str = "",
    with_since: bool = False,
    with_since_days: bool = False,
    add_args: Callable[[argparse.ArgumentParser], None] | None = None,
    make_extra_kwargs: Callable[[argparse.Namespace],
                                dict[str, Any]] | None = None
) -> Callable[[list[str] | None], None]:
    """Generate a ``main(argv)`` function for a pipeline CLI.

    Args:
        pipeline_cls: Pipeline class to instantiate.  Must accept ``store``
            kwarg and optionally extra kwargs from ``make_extra_kwargs``.
        description: ``argparse`` help text.
        with_since: Add ``--since`` (ISO 8601 or relative, e.g. ``7d``).
            Parsed value is forwarded as ``since=<datetime>`` to ``run()``.
        with_since_days: Add ``--since-days`` (int; 0 = full history).
            Computes a ``datetime`` and passes it as ``since=<datetime>``.
        add_args: Hook to add extra ``argparse`` arguments to the parser.
        make_extra_kwargs: Extract extra pipeline constructor kwargs from the
            parsed ``Namespace``.  Called after all standard resolution.
    """

    def main(argv: list[str] | None = None) -> None:
        parser = argparse.ArgumentParser(description=description)
        if with_since:
            parser.add_argument("--since", default=None, help=_SINCE_HELP)
        if with_since_days:
            parser.add_argument("--since-days", type=int,
                                default=0, help=_SINCE_DAYS_HELP)
        if add_args:
            add_args(parser)
        args = parser.parse_args(argv)

        load_dotenv()
        setup_logging()
        logger = get_logger(pipeline_cls.__module__)

        # Resolve since
        since: dt.datetime | None = None
        if with_since:
            try:
                since = _parse_since(args.since)
            except ValueError as exc:
                parser.error(str(exc))
                return
        elif with_since_days:
            days = getattr(args, "since_days", 0)
            if days and days > 0:
                since = dt.datetime.now(
                    dt.timezone.utc) - dt.timedelta(days=days)

        # Build pipeline kwargs
        store = ArangoStore()
        kwargs: dict[str, Any] = {"store": store}
        if make_extra_kwargs:
            kwargs.update(make_extra_kwargs(args))

        pipeline = pipeline_cls(**kwargs)
        try:
            result = pipeline.run(since=since)
        except Exception as exc:
            logger.error("%s failed: %s", pipeline_cls.__name__, exc)
            sys.exit(1)

        logger.info("%s: %s.", pipeline_cls.__name__, result.summary())
        if result.errors:
            for err in result.errors:
                logger.warning("%s error: %s", pipeline_cls.__name__, err)
            sys.exit(1)

    return main
