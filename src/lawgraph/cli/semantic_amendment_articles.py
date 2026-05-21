"""CLI for detecting legislative amendment language and creating semantic edges."""

from __future__ import annotations

import argparse
import datetime as dt
import sys

from dotenv import load_dotenv

from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger, setup_logging
from lawgraph.pipelines.semantic.amendment_articles import AmendmentArticlePipeline

logger = get_logger(__name__)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Detect Dutch legislative amendment language and create"
            " WIJZIGT/INTRODUCEERT/TREKT_IN edges."
        )
    )
    parser.add_argument(
        "--since-days",
        type=int,
        default=0,
        help="Look back this many days; 0 means full history.",
    )
    args = parser.parse_args(argv)

    load_dotenv()
    setup_logging()

    if args.since_days and args.since_days > 0:
        since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.since_days)
    else:
        since = None

    store = ArangoStore()
    pipeline = AmendmentArticlePipeline(store=store)

    logger.info(
        "Starting amendment article linker (since=%s).",
        since.isoformat() if since else "full",
    )
    result = pipeline.run(since=since)
    logger.info("Amendment article linker: %s.", result.summary())
    if result.errors:
        for err in result.errors:
            logger.warning("Amendment linker error: %s", err)
        sys.exit(1)
