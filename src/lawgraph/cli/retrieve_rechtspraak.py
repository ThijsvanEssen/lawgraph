from __future__ import annotations

"""CLI for retrieving Rechtspraak index snapshots and content."""

import argparse
import datetime as dt
import os

from dotenv import load_dotenv

from lawgraph.config import list_domain_profiles
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger, setup_logging
from lawgraph.pipelines.retrieve.rechtspraak import RechtspraakRetrievePipeline

from .retrieve_helpers import (
    load_profile_config,
    build_rechtspraak_params,
    seed_examples,
)

logger = get_logger(__name__)
PROFILE_CHOICES = list_domain_profiles()


def main(argv: list[str] | None = None) -> None:
    """Entry point to fetch Rechtspraak snapshots and specific ECLI contents."""
    parser = argparse.ArgumentParser(
        description="Retrieve Rechtspraak index and contents.")
    parser.add_argument(
        "--profile",
        choices=PROFILE_CHOICES or None,
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
    args = parser.parse_args(argv)

    load_dotenv()
    setup_logging()

    profile = args.profile or os.getenv("LAWGRAPH_PROFILE")
    logger.info("Starting Rechtspraak retrieve (profile=%s).", profile or "default")

    store = ArangoStore()
    pipeline = RechtspraakRetrievePipeline(store)

    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.since_days)
    config = load_profile_config(profile)

    params = build_rechtspraak_params(
        config.get("filters", {}).get("rechtspraak", {}))
    eclis: list[str] = []
    if args.ecli:
        eclis = args.ecli
    elif config:
        eclis = list(seed_examples(config).get("rechtspraak_eclis", []))

    pipeline.dump(
        fetch_index=True,
        since=since,
        extra_params=params,
        eclis=eclis,
    )

    logger.info(
        "Rechtspraak retrieve run completed (profile=%s).",
        profile or "default",
    )
