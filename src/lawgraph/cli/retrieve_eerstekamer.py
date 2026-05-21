"""CLI for retrieving Eerste Kamer Kamerstukken."""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger, setup_logging
from lawgraph.pipelines.retrieve.eerstekamer import EerstekamerRetrievePipeline

logger = get_logger(__name__)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Retrieve Eerste Kamer Kamerstukken.")
    parser.add_argument(
        "--since",
        help="ISO date (YYYY-MM-DD) for incremental retrieval.",
    )
    parser.add_argument(
        "--max-records",
        type=int,
        default=50000,
        help="Maximum number of records to fetch (default: 50000).",
    )
    parser.add_argument(
        "--mode",
        choices=["incremental", "full"],
        default="incremental",
        help="'incremental' uses --since; 'full' fetches all available records.",
    )
    parser.add_argument("--profile", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    load_dotenv()
    setup_logging()

    mode = args.mode
    since = args.since if mode == "incremental" else None

    logger.info(
        "Starting Eerste Kamer retrieve (mode=%s, since=%s).", mode, since or "all"
    )

    store = ArangoStore()
    pipeline = EerstekamerRetrievePipeline(store)

    max_records = args.max_records if mode == "incremental" else 200000
    result = pipeline.run(since=since, max_records=max_records)

    logger.info("Eerste Kamer retrieve completed: %s.", result.summary())
    if result.errors:
        for err in result.errors:
            logger.warning("EK retrieve error: %s", err)
        sys.exit(1)
