"""CLI entry point for the MvT article-to-article semantic pipeline (LICHT_TOE)."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

from dotenv import load_dotenv

from lawgraph.cli.retrieve_helpers import load_profile_config
from lawgraph.config import list_domain_profiles
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger, setup_logging
from lawgraph.pipelines.semantic.mvt_articles import MvtArticleSemanticPipeline

logger = get_logger(__name__)


def _parse_since(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    value = value.strip()
    if value.endswith("d") and value[:-1].isdigit():
        return dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=int(value[:-1]))
    try:
        parsed = dt.datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed
    except ValueError as exc:
        raise ValueError(f"Cannot parse --since value '{value}'.") from exc


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Link MvT/NvT publications to instrument articles via LICHT_TOE edges. "
            "Scans publications whose soort contains 'toelichting' for the "
            "'Artikelsgewijze toelichting' section."
        )
    )
    parser.add_argument(
        "--profile",
        choices=list_domain_profiles() or None,
        help="Domain profile to scope the semantic linking.",
    )
    parser.add_argument(
        "--since",
        default=None,
        help="Only process records fetched since this date (ISO 8601 or '7d').",
    )
    args = parser.parse_args(argv)

    load_dotenv()
    setup_logging()

    profile = args.profile or os.getenv("LAWGRAPH_PROFILE")

    try:
        since = _parse_since(args.since)
    except ValueError as exc:
        parser.error(str(exc))
        return

    store = ArangoStore()
    config = load_profile_config(profile)
    pipeline = MvtArticleSemanticPipeline(
        store=store,
        domain_profile=profile,
        domain_config=config,
    )

    logger.info(
        "Starting MvT article semantic pipeline (profile=%s, since=%s).",
        profile or "default",
        args.since or "all",
    )
    result = pipeline.run(since=since)
    logger.info("MvT article semantic pipeline: %s.", result.summary())
    if result.errors:
        for err in result.errors:
            logger.warning("MvT semantic error: %s", err)
        sys.exit(1)
