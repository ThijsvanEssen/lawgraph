"""CLI for normalizing Eerste Kamer Kamerstukken."""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger, setup_logging
from lawgraph.pipelines.normalize.eerstekamer import EerstekamerNormalizePipeline

logger = get_logger(__name__)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Normalize Eerste Kamer Kamerstukken.")
    parser.parse_args(argv)

    load_dotenv()
    setup_logging()

    logger.info("Starting Eerste Kamer normalize.")

    store = ArangoStore()
    pipeline = EerstekamerNormalizePipeline(store=store)
    result = pipeline.run()

    logger.info("Eerste Kamer normalize completed: %s.", result.summary())
    if result.errors:
        for err in result.errors:
            logger.warning("EK normalize error: %s", err)
        sys.exit(1)
