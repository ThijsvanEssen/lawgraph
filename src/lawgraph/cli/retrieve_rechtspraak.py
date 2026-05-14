"""CLI for retrieving Rechtspraak index snapshots and content."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

from dotenv import load_dotenv

from lawgraph.config import list_domain_profiles
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger, setup_logging
from lawgraph.pipelines.retrieve.rechtspraak import RechtspraakRetrievePipeline

from .retrieve_helpers import (
    build_rechtspraak_params,
    load_profile_config,
    seed_examples,
)

logger = get_logger(__name__)


def main(argv: list[str] | None = None) -> None:
    """Entry point to fetch Rechtspraak snapshots and specific ECLI contents."""
    parser = argparse.ArgumentParser(
        description="Retrieve Rechtspraak index and contents."
    )
    parser.add_argument(
        "--profile",
        choices=list_domain_profiles() or None,
        help="Optional domain profile for filtering (currently only strafrecht).",
    )
    parser.add_argument(
        "--since-days",
        type=int,
        default=1,
        help="Number of days to look back when fetching the index snapshot.",
    )
    parser.add_argument(
        "--ecli",
        action="append",
        help="Explicit ECLI(s) to fetch content for; uses profile seeds if omitted.",
    )
    parser.add_argument(
        "--mode",
        choices=["incremental", "full"],
        default="incremental",
        help=(
            "'incremental' fetches index since --since-days (default); "
            "'full' paginates the entire Rechtspraak index without a date filter."
        ),
    )
    args = parser.parse_args(argv)

    load_dotenv()
    setup_logging()

    profile = args.profile or os.getenv("LAWGRAPH_PROFILE")
    mode = args.mode
    logger.info(
        "Starting Rechtspraak retrieve (profile=%s, mode=%s).",
        profile or "default",
        mode,
    )

    store = ArangoStore()
    pipeline = RechtspraakRetrievePipeline(store)

    if mode == "full":
        logger.info("Full-load mode: paginating entire Rechtspraak index.")
        config = load_profile_config(profile)
        params = build_rechtspraak_params(
            config.get("filters", {}).get("rechtspraak", {})
        )
        result = pipeline.run_full(extra_params=params or None)
    else:
        since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.since_days)
        config = load_profile_config(profile)

        params = build_rechtspraak_params(
            config.get("filters", {}).get("rechtspraak", {})
        )
        eclis: list[str] = []
        if args.ecli:
            eclis = args.ecli
        elif config:
            eclis = list(seed_examples(config).get("rechtspraak_eclis", []))

        result = pipeline.run(
            fetch_index=True,
            since=since,
            extra_params=params,
            eclis=eclis,
        )

    logger.info(
        "Rechtspraak retrieve completed (profile=%s, mode=%s): %s.",
        profile or "default",
        mode,
        result.summary(),
    )
    if result.errors:
        for err in result.errors:
            logger.warning("Rechtspraak retrieve error: %s", err)
        sys.exit(1)
