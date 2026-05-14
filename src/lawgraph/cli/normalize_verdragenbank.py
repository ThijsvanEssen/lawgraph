"""CLI for normalizing Verdragenbank treaty records."""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger, setup_logging
from lawgraph.pipelines.normalize.verdragenbank import VerdragenbankNormalizePipeline

logger = get_logger(__name__)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Normalize Verdragenbank treaty records."
    )
    parser.add_argument("--profile", help=argparse.SUPPRESS)
    parser.parse_args(argv)

    load_dotenv()
    setup_logging()

    logger.info("Starting Verdragenbank normalize.")

    store = ArangoStore()
    pipeline = VerdragenbankNormalizePipeline(store=store)
    result = pipeline.run()

    logger.info("Verdragenbank normalize completed: %s.", result.summary())
    if result.errors:
        for err in result.errors:
            logger.warning("Verdragenbank normalize error: %s", err)
        sys.exit(1)
