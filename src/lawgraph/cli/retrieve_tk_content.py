"""CLI for fetching and storing full-text content for TK publications (MvT etc.)."""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger, setup_logging
from lawgraph.pipelines.retrieve.tk_content import TKTextHydratePipeline

logger = get_logger(__name__)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch full-text PDF content for TK publications and store it in "
            "props.text so the semantic pipeline can link them to articles."
        )
    )
    parser.add_argument(
        "--soort",
        default="toelichting",
        help=(
            "Case-insensitive substring matched against props.soort. "
            "Default: 'toelichting' (catches MvT, Nota van toelichting, etc.)."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log what would be fetched without making any changes.",
    )
    args = parser.parse_args(argv)

    load_dotenv()
    setup_logging()

    store = ArangoStore()
    pipeline = TKTextHydratePipeline(store=store)

    logger.info(
        "Starting TK content hydration (soort='%s', dry_run=%s).",
        args.soort,
        args.dry_run,
    )
    result = pipeline.run(soort_filter=args.soort, dry_run=args.dry_run)
    logger.info("Done: %s.", result.summary())

    if result.errors:
        for err in result.errors:
            logger.warning("Error: %s", err)
        sys.exit(1)
