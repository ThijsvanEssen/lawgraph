"""CLI entry point for the BWB article-to-article semantic pipeline."""

from __future__ import annotations

import argparse
import os

from dotenv import load_dotenv

from lawgraph.cli.retrieve_helpers import load_profile_config
from lawgraph.config import list_domain_profiles
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger, setup_logging
from lawgraph.pipelines.semantic.bwb_articles import BwbArticlesSemanticPipeline

logger = get_logger(__name__)
PROFILE_CHOICES = list_domain_profiles()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Detect BWB article references and store semantic REFERS_TO_ARTICLE edges."
    )
    parser.add_argument(
        "--profile",
        choices=PROFILE_CHOICES or None,
        help="Domain profile that defines target BWB IDs (default: strafrecht).",
    )
    parser.add_argument(
        "--store-citations",
        action="store_true",
        help="Store detected citations on the source article documents.",
    )

    args = parser.parse_args(argv)

    load_dotenv()
    setup_logging()

    profile = args.profile or os.getenv("LAWGRAPH_PROFILE")
    store = ArangoStore()
    config = load_profile_config(profile)
    pipeline = BwbArticlesSemanticPipeline(
        store=store,
        domain_profile=profile,
        domain_config=config,
        store_citations=args.store_citations,
    )

    logger.info(
        "Starting BWB article semantic pipeline (profile=%s, store_citations=%s).",
        profile or "default",
        args.store_citations,
    )
    created = pipeline.run()
    logger.info("Created %d REFERS_TO_ARTICLE edges.", created)
