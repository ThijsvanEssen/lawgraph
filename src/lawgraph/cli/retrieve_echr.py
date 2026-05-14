"""CLI for retrieving ECHR HUDOC judgments."""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger, setup_logging
from lawgraph.pipelines.retrieve.echr import EchrRetrievePipeline

logger = get_logger(__name__)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Retrieve ECHR HUDOC judgments.")
    parser.add_argument(
        "--respondent",
        default="NLD",
        help="Three-letter country code for the respondent (default: NLD).",
    )
    parser.add_argument(
        "--since",
        help="ISO date (YYYY-MM-DD) for incremental retrieval.",
    )
    parser.add_argument(
        "--max-records",
        type=int,
        default=10000,
        help="Maximum number of records to fetch (default: 10000).",
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
    max_records = args.max_records if mode == "incremental" else 50000

    logger.info(
        "Starting ECHR retrieve (mode=%s, respondent=%s, since=%s).",
        mode,
        args.respondent,
        since or "all",
    )

    store = ArangoStore()
    pipeline = EchrRetrievePipeline(store)

    if mode == "full":
        result = pipeline.run_full(respondent=args.respondent)
    else:
        result = pipeline.run(
            respondent=args.respondent,
            since_date=since,
            max_records=max_records,
        )

    logger.info("ECHR retrieve completed: %s.", result.summary())
    if result.errors:
        for err in result.errors:
            logger.warning("ECHR retrieve error: %s", err)
        sys.exit(1)
