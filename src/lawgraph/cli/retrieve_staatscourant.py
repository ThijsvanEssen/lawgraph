"""CLI for retrieving Dutch Staatscourant ministeriele regelingen."""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger, setup_logging
from lawgraph.pipelines.retrieve.staatscourant import StaatscourantRetrievePipeline

logger = get_logger(__name__)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Retrieve Staatscourant ministeriele regelingen."
    )
    parser.add_argument(
        "--since",
        help="ISO date (YYYY-MM-DD) for incremental retrieval.",
    )
    parser.add_argument(
        "--mode",
        choices=["incremental", "full"],
        default="incremental",
        help="'incremental' uses --since; 'full' enumerates all records.",
    )
    parser.add_argument(
        "--identifiers",
        nargs="*",
        help="Explicit Staatscourant identifiers to fetch (e.g. stcrt-2023-12345).",
    )
    parser.add_argument("--profile", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    load_dotenv()
    setup_logging()

    mode = args.mode
    logger.info("Starting Staatscourant retrieve (mode=%s).", mode)

    store = ArangoStore()
    pipeline = StaatscourantRetrievePipeline(store)

    if args.identifiers:
        result = pipeline.run(identifiers=args.identifiers)
    elif mode == "full":
        result = pipeline.run_full()
    else:
        result = pipeline.run(since=args.since)

    logger.info("Staatscourant retrieve completed: %s.", result.summary())
    if result.errors:
        for err in result.errors:
            logger.warning("Staatscourant retrieve error: %s", err)
        sys.exit(1)
