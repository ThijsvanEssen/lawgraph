"""CLI for retrieving Tweede Kamer Zaak and DocumentVersie records."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

from dotenv import load_dotenv

from lawgraph.config import list_domain_profiles
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger, setup_logging
from lawgraph.pipelines.retrieve.tk import TKRetrievePipeline

from .retrieve_helpers import load_profile_config, make_tk_filter

logger = get_logger(__name__)

# Earliest date the TK OData API holds records for.
_TK_EPOCH = dt.datetime(1995, 1, 1, tzinfo=dt.timezone.utc)


def main(argv: list[str] | None = None) -> None:
    """Entry point for the TK retrieve pipeline using the selected profile filters."""
    parser = argparse.ArgumentParser(
        description="Retrieve TK zaak and documentversie data."
    )
    parser.add_argument(
        "--profile",
        choices=list_domain_profiles() or None,
        help="Optional domain profile for filtering (currently only strafrecht).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help=(
            "Hard cap on records fetched per endpoint, for development/smoke-test runs. "
            "0 (default) means no cap — all pages are fetched via OData nextLink pagination."
        ),
    )
    parser.add_argument(
        "--since-days",
        type=int,
        default=1,
        help="Amount of days to look back for modified TK records.",
    )
    parser.add_argument(
        "--mode",
        choices=["incremental", "full"],
        default="incremental",
        help=(
            "'incremental' fetches records modified since --since-days (default); "
            f"'full' fetches all records since {_TK_EPOCH.date().isoformat()} via OData pagination."
        ),
    )
    args = parser.parse_args(argv)

    load_dotenv()
    setup_logging()

    profile = args.profile or os.getenv("LAWGRAPH_PROFILE")
    mode = args.mode

    if mode == "full":
        since = _TK_EPOCH
    else:
        since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.since_days)

    logger.info(
        "Starting TK retrieve (profile=%s, mode=%s, since=%s%s).",
        profile or "default",
        mode,
        since.isoformat(),
        f", dev cap={args.limit}" if args.limit else "",
    )

    store = ArangoStore()
    pipeline = TKRetrievePipeline(store)

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
        "TK retrieve completed (profile=%s, mode=%s): %s.",
        profile or "default",
        mode,
        result.summary(),
    )
    if result.errors:
        for err in result.errors:
            logger.warning("TK retrieve error: %s", err)
        sys.exit(1)
