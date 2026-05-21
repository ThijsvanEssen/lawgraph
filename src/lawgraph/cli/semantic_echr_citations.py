"""CLI: semantic pipeline linking ECHR judgments to cited articles and instruments."""

from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv

from lawgraph.config import list_domain_profiles
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger, setup_logging
from lawgraph.pipelines.semantic.echr_citations import EchrCitationsPipeline

logger = get_logger(__name__)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Create CITES_ARTICLE edges from ECHR judgments to ECHR Convention articles, "
            "and MENTIONS_INSTRUMENT edges to NL instruments referenced in the conclusion."
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
    logger.info("ECHR citations semantic: starting (profile=%s).", profile or "default")

    store = ArangoStore()
    pipeline = EchrCitationsPipeline(store=store, domain_profile=profile)
    result = pipeline.run()

    logger.info("ECHR citations semantic completed: %s.", result.summary())
    if result.errors:
        for err in result.errors:
            logger.warning("ECHR citations error: %s", err)
        sys.exit(1)
