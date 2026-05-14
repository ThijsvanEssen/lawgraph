"""CLI: semantic pipeline for BWB grondslagen → DELEGATED_BY edges."""

from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv

from lawgraph.config import list_domain_profiles
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger, setup_logging
from lawgraph.pipelines.semantic.bwb_grondslagen import BWBGrondslagenSemanticPipeline

logger = get_logger(__name__)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Create DELEGATED_BY edges from BWB AMvB grondslagen."
    )
    parser.add_argument(
        "--profile",
        choices=list_domain_profiles() or None,
        help="Domain profile (unused here, accepted for orchestrator compatibility).",
    )
    args = parser.parse_args(argv)

    load_dotenv()
    setup_logging()

    profile = args.profile or os.getenv("LAWGRAPH_PROFILE")
    logger.info(
        "BWB grondslagen semantic: starting (profile=%s).", profile or "default"
    )

    store = ArangoStore()
    pipeline = BWBGrondslagenSemanticPipeline(store=store, domain_profile=profile)
    result = pipeline.run()

    logger.info("BWB grondslagen semantic completed: %s.", result.summary())
    if result.errors:
        for err in result.errors:
            logger.warning("BWB grondslagen error: %s", err)
        sys.exit(1)
