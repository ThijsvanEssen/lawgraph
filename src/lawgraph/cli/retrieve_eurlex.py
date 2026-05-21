"""CLI for retrieving EUR-Lex records based on configurable CELEX lists."""

from __future__ import annotations

import argparse
import os
import sys

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


def main(argv: list[str] | None = None) -> None:
    """Run the EUR-Lex retrieve pipeline with the selected profile and CELEX list."""
    parser = argparse.ArgumentParser(description="Retrieve EUR-Lex CELEX html pages.")
    parser.add_argument(
        "--profile",
        choices=list_domain_profiles() or None,
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
    parser.add_argument(
        "--country",
        default="NLD",
        help="Three-letter country code for NIM mode (default: NLD = Netherlands).",
    )
    parser.add_argument(
        "--mode",
        choices=["incremental", "full", "nim", "cjeu", "com"],
        default="incremental",
        help=(
            "'incremental' uses the provided CELEX IDs/profile; "
            "'full' enumerates all regulations, directives and decisions via CELLAR SPARQL; "
            "'nim' enumerates EU acts that have national implementation measures for --country; "
            "'cjeu' enumerates CJEU judgments citing instruments in the graph; "
            "'com' enumerates COM proposals for instruments in the graph."
        ),
    )
    args = parser.parse_args(argv)

    load_dotenv()
    setup_logging()
    profile = args.profile or os.getenv("LAWGRAPH_PROFILE")
    mode = args.mode
    logger.info(
        "Starting EUR-Lex retrieve (profile=%s, mode=%s).", profile or "default", mode
    )

    store = ArangoStore()
    pipeline = EurlexRetrievePipeline(store)

    if mode == "full":
        logger.info(
            "Full-load mode: enumerating all EUR-Lex documents via CELLAR SPARQL."
        )
        result = pipeline.run_full(lang=args.lang)
    elif mode == "nim":
        country = args.country
        logger.info(
            "NIM mode: enumerating EU acts with national implementation measures (country=%s).",
            country,
        )
        result = pipeline.run_nim(country_code=country, lang=args.lang)
    elif mode == "cjeu":
        logger.info(
            "CJEU mode: enumerating judgment CELEX IDs for instruments in the graph."
        )
        aql = "FOR inst IN instruments FILTER inst.props.celex != null RETURN inst.props.celex"
        existing_celex = list(store.query(aql))
        result = pipeline.run_cjeu(
            celex_ids=existing_celex or None,
            country_code=args.country,
            lang=args.lang,
        )
    elif mode == "com":
        logger.info(
            "COM mode: enumerating COM proposal CELEX IDs for instruments in the graph."
        )
        aql = "FOR inst IN instruments FILTER inst.props.celex != null RETURN inst.props.celex"
        existing_celex = list(store.query(aql))
        result = pipeline.run_com(celex_ids=existing_celex, lang=args.lang)
    else:
        config = load_profile_config(profile)
        filters = eurlex_filters(config)
        seeds = seed_examples(config)
        candidates = args.celex or merge_celex_ids(filters, seeds)

        if not candidates:
            logger.warning("No EUR-Lex CELEX identifiers were provided or configured.")
            return

        result = pipeline.run(
            celex_ids=candidates,
            lang=args.lang,
        )

    logger.info(
        "EUR-Lex retrieve completed (profile=%s, mode=%s): %s.",
        profile or "default",
        mode,
        result.summary(),
    )
    if result.errors:
        for err in result.errors:
            logger.warning("EUR-Lex retrieve error: %s", err)
        sys.exit(1)
