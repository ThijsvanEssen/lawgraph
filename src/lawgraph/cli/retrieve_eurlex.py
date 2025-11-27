"""CLI for retrieving EUR-Lex records based on configurable CELEX lists."""

from __future__ import annotations

import argparse
import os

from dotenv import load_dotenv

from lawgraph.config import list_domain_profiles
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger, setup_logging
from lawgraph.pipelines.retrieve.eurlex import EurlexRetrievePipeline

from .retrieve_helpers import (
    eurlex_filters,
    load_profile_config,
    merge_celex_ids,
    seed_examples,
)

logger = get_logger(__name__)
PROFILE_CHOICES = list_domain_profiles()


def main(argv: list[str] | None = None) -> None:
    """Run the EUR-Lex retrieve pipeline with the selected profile and CELEX list."""
    parser = argparse.ArgumentParser(description="Retrieve EUR-Lex CELEX html pages.")
    parser.add_argument(
        "--profile",
        choices=PROFILE_CHOICES or None,
        help="Optional domain profile for filtering (currently only strafrecht).",
    )
    parser.add_argument(
        "--celex",
        action="append",
        help="Explicit CELEX identifier(s) to fetch; uses profile filters if omitted.",
    )
    parser.add_argument(
        "--lang",
        default="NL",
        help="Language code for the EUR-Lex html fetch (default: NL).",
    )
    args = parser.parse_args(argv)

    load_dotenv()
    setup_logging()
    profile = args.profile or os.getenv("LAWGRAPH_PROFILE")
    logger.info("Starting EUR-Lex retrieve (profile=%s).", profile or "default")

    store = ArangoStore()
    pipeline = EurlexRetrievePipeline(store)

    config = load_profile_config(profile)
    filters = eurlex_filters(config)
    seeds = seed_examples(config)
    candidates = args.celex or merge_celex_ids(filters, seeds)

    if not candidates:
        logger.warning("No EUR-Lex CELEX identifiers were provided or configured.")
        return

    pipeline.dump(
        celex_ids=candidates,
        lang=args.lang,
    )

    logger.info("EUR-Lex retrieve run completed (profile=%s).", profile or "default")
