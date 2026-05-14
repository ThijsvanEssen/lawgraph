"""CLI for normalizing Staatscourant ministeriele regelingen."""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger, setup_logging
from lawgraph.pipelines.normalize.staatscourant import StaatscourantNormalizePipeline

logger = get_logger(__name__)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Normalize Staatscourant ministeriele regelingen."
    )
    parser.parse_args(argv)

    load_dotenv()
    setup_logging()

    logger.info("Starting Staatscourant normalize.")

    store = ArangoStore()
    pipeline = StaatscourantNormalizePipeline(store=store)
    result = pipeline.run()

    logger.info("Staatscourant normalize completed: %s.", result.summary())
    if result.errors:
        for err in result.errors:
            logger.warning("Staatscourant normalize error: %s", err)
        sys.exit(1)
