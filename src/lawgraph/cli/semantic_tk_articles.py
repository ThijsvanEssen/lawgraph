"""CLI for linking TK documents to articles via semantic edges."""

from __future__ import annotations

import argparse
import datetime as dt
import os

from dotenv import load_dotenv

from lawgraph.cli.retrieve_helpers import load_profile_config
from lawgraph.config import list_domain_profiles
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger, setup_logging
from lawgraph.pipelines.semantic.tk_articles import TKArticleSemanticPipeline

logger = get_logger(__name__)
PROFILE_CHOICES = list_domain_profiles()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Detect TK references to Dutch and EU articles via semantic edges."
    )
    parser.add_argument(
        "--profile",
        choices=PROFILE_CHOICES or None,
        help="Domain profile that contains alias mappings (e.g. strafrecht).",
    )
    parser.add_argument(
        "--since-days",
        type=int,
        default=0,
        help="Look back this many days; 0 means full history.",
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
    pipeline = TKArticleSemanticPipeline(
        store=store,
        domain_profile=profile,
        domain_config=config,
    )

    logger.info(
        "Starting TK semantic article linker (profile=%s, since=%s).",
        profile or "default",
        since.isoformat() if since else "full",
    )
    created = pipeline.run(since=since)
    logger.info("TK semantic pipeline created %d edges.", created)
