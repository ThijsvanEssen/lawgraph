"""CLI: semantic pipeline linking Staatscourant regelingen to BWB instruments."""

from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv

from lawgraph.config import list_domain_profiles
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger, setup_logging
from lawgraph.pipelines.semantic.staatscourant_regeling import (
    StaatscourantRegelingSemanticPipeline,
)

logger = get_logger(__name__)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Create EXPLAINS_INSTRUMENT edges from Staatscourant regelingen to BWB instruments."
        )
    )
    parser.add_argument(
        "--profile",
        choices=list_domain_profiles() or None,
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args(argv)

    load_dotenv()
    setup_logging()

    profile = args.profile or os.getenv("LAWGRAPH_PROFILE")
    logger.info(
        "Staatscourant regeling semantic: starting (profile=%s).", profile or "default"
    )

    store = ArangoStore()
    pipeline = StaatscourantRegelingSemanticPipeline(
        store=store, domain_profile=profile
    )
    result = pipeline.run()

    logger.info("Staatscourant regeling semantic completed: %s.", result.summary())
    if result.errors:
        for err in result.errors:
            logger.warning("Staatscourant regeling error: %s", err)
        sys.exit(1)
