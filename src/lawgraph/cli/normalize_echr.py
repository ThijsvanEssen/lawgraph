"""CLI for normalizing ECHR HUDOC judgments."""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger, setup_logging
from lawgraph.pipelines.normalize.echr import EchrNormalizePipeline

logger = get_logger(__name__)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Normalize ECHR HUDOC judgments.")
    parser.parse_args(argv)

    load_dotenv()
    setup_logging()

    logger.info("Starting ECHR normalize.")

    store = ArangoStore()
    pipeline = EchrNormalizePipeline(store=store)
    result = pipeline.run()

    logger.info("ECHR normalize completed: %s.", result.summary())
    if result.errors:
        for err in result.errors:
            logger.warning("ECHR normalize error: %s", err)
        sys.exit(1)
