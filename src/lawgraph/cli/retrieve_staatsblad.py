"""CLI entry point for retrieving Dutch Staatsblad AMvB publications."""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger, setup_logging
from lawgraph.pipelines.retrieve.staatsblad import StaatsbladRetrievePipeline

logger = get_logger(__name__)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Retrieve Dutch Staatsblad AMvB XML publications."
    )
    parser.add_argument(
        "--mode",
        choices=["from-graph", "full"],
        default="from-graph",
        help=(
            "'from-graph' uses existing BWB raw_sources to find Staatsblad refs "
            "(default); 'full' searches the SRU endpoint for all AMvBs."
        ),
    )
    args = parser.parse_args(argv)

    load_dotenv()
    setup_logging()

    store = ArangoStore()
    pipeline = StaatsbladRetrievePipeline(store=store)

    logger.info("Starting Staatsblad retrieve (mode=%s).", args.mode)

    if args.mode == "full":
        result = pipeline.run_full()
    else:
        result = pipeline.run_from_bwb_graph(store)

    logger.info(
        "Staatsblad retrieve completed (mode=%s): %s.",
        args.mode,
        result.summary(),
    )
    if result.errors:
        for err in result.errors:
            logger.warning("Staatsblad retrieve error: %s", err)
        sys.exit(1)
