"""CLI for the EU instrument → article semantic linker."""

from __future__ import annotations

import argparse
import datetime as dt
import os

from dotenv import load_dotenv

from lawgraph.cli.retrieve_helpers import load_profile_config
from lawgraph.config import list_domain_profiles
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger, setup_logging
from lawgraph.pipelines.semantic.eu_articles import EUArticleSemanticPipeline

logger = get_logger(__name__)
PROFILE_CHOICES = list_domain_profiles()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Link EU instruments to national/EU articles via semantic edges."
    )
    parser.add_argument(
        "--profile",
        choices=PROFILE_CHOICES or None,
        help="Domain profile that holds code alias mappings (e.g. strafrecht).",
    )
    parser.add_argument(
        "--since-days",
        type=int,
        default=0,
        help="Only consider documents modified in the last N days (0 = all history).",
    )
    args = parser.parse_args(argv)

    load_dotenv()
    setup_logging()

    profile = args.profile or os.getenv("LAWGRAPH_PROFILE")
    if args.since_days and args.since_days > 0:
        since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.since_days)
    else:
        since = None

    store = ArangoStore()
    config = load_profile_config(profile)
    pipeline = EUArticleSemanticPipeline(
        store=store,
        domain_profile=profile,
        domain_config=config,
    )

    logger.info(
        "Starting EU semantic article linker (profile=%s, since=%s).",
        profile or "default",
        since.isoformat() if since else "full",
    )
    created = pipeline.run(since=since)
    logger.info("EU semantic pipeline created %d edges.", created)
