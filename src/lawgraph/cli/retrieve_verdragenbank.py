"""CLI for retrieving Dutch Verdragenbank (treaty register) data."""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger, setup_logging
from lawgraph.pipelines.retrieve.verdragenbank import VerdragenbankRetrievePipeline

logger = get_logger(__name__)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Retrieve treaties from the Dutch Verdragenbank."
    )
    parser.add_argument(
        "--max-records",
        type=int,
        default=10000,
        help="Maximum number of treaties to fetch (default: 10000).",
    )
    parser.add_argument(
        "--mode",
        choices=["incremental", "full"],
        default="full",
        help="'full' fetches all treaties (incremental not supported by SPARQL endpoint).",
    )
    parser.add_argument("--profile", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    load_dotenv()
    setup_logging()

    logger.info("Starting Verdragenbank retrieve (max_records=%d).", args.max_records)

    store = ArangoStore()
    pipeline = VerdragenbankRetrievePipeline(store)
    result = pipeline.run(max_records=args.max_records)

    logger.info("Verdragenbank retrieve completed: %s.", result.summary())
    if result.errors:
        for err in result.errors:
            logger.warning("Verdragenbank retrieve error: %s", err)
        sys.exit(1)
