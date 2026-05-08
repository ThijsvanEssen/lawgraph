"""CLI for retrieving Tweede Kamer Zaak and DocumentVersie records."""

from __future__ import annotations

import argparse
import datetime as dt
import os

from dotenv import load_dotenv

from lawgraph.config import list_domain_profiles
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger, setup_logging
from lawgraph.pipelines.retrieve.tk import TKRetrievePipeline

from .retrieve_helpers import load_profile_config, make_tk_filter

logger = get_logger(__name__)
PROFILE_CHOICES = list_domain_profiles()


def main(argv: list[str] | None = None) -> None:
    """Entry point for the TK retrieve pipeline using the selected profile filters."""
    parser = argparse.ArgumentParser(
        description="Retrieve TK zaak and documentversie data."
    )
    parser.add_argument(
        "--profile",
        choices=PROFILE_CHOICES or None,
        help="Optional domain profile for filtering (currently only strafrecht).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum number of records per TK endpoint.",
    )
    parser.add_argument(
        "--since-days",
        type=int,
        default=1,
        help="Amount of days to look back for modified TK records.",
    )
    args = parser.parse_args(argv)

    load_dotenv()
    setup_logging()

    profile = args.profile or os.getenv("LAWGRAPH_PROFILE")

    store = ArangoStore()
    pipeline = TKRetrievePipeline(store)

    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.since_days)

    logger.info(
        "Starting TK retrieve (profile=%s, limit=%d, since=%s).",
        profile or "default",
        args.limit,
        since.isoformat(),
    )
    config = load_profile_config(profile)
    tk_filter = None
    keywords: list[str] | None = None
    if config:
        tk_cfg = config.get("filters", {}).get("tk", {})
        tk_filter = make_tk_filter(tk_cfg)
        all_keywords = [
            kw.strip()
            for kw in tk_cfg.get("title_contains", [])
            if isinstance(kw, str) and kw.strip()
        ]
        # TK OData API rejects filters with too many OR clauses (fields × keywords).
        # Pass at most 3 short keywords for server-side pre-filtering; the full
        # make_tk_filter runs client-side on every returned record.
        _MAX_API_KEYWORDS = 3
        keywords = all_keywords[:_MAX_API_KEYWORDS] or None

    result = pipeline.run(
        since=since,
        limit=args.limit,
        zaak_filter=tk_filter,
        documentversie_filter=tk_filter,
        keywords=keywords,
    )

    logger.info(
        "TK retrieve completed (profile=%s): %s.",
        profile or "default",
        result.summary(),
    )
    if result.errors:
        for err in result.errors:
            logger.warning("TK retrieve error: %s", err)
