"""CLI for detecting ECLI cross-references between judgments (CITES_JUDGMENT)."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

from dotenv import load_dotenv

from lawgraph.config import list_domain_profiles
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger, setup_logging
from lawgraph.pipelines.semantic.judgment_citations import (
    JudgmentCitationsSemanticPipeline,
)

logger = get_logger(__name__)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Detect ECLI cross-references in judgments and create CITES_JUDGMENT edges."
    )
    parser.add_argument(
        "--profile",
        choices=list_domain_profiles() or None,
        help="Domain profile (optional; no aliases needed for ECLI detection).",
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
    since = (
        dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.since_days)
        if args.since_days and args.since_days > 0
        else None
    )

    store = ArangoStore()
    pipeline = JudgmentCitationsSemanticPipeline(store=store, domain_profile=profile)

    logger.info(
        "Starting judgment citation linker (profile=%s, since=%s).",
        profile or "default",
        since.isoformat() if since else "full",
    )
    result = pipeline.run(since=since)
    logger.info("Judgment citation linker: %s.", result.summary())
    if result.errors:
        for err in result.errors:
            logger.warning("Judgment citation error: %s", err)
        sys.exit(1)
