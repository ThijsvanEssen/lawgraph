"""CLI: normalize raw TK dossier records into graph nodes and edges.

Usage:
  lawgraph-normalize-tk-dossiers           # normalize all raw records
  lawgraph-normalize-tk-dossiers --since 7d  # only records fetched recently
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys

from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger
from lawgraph.pipelines.normalize.tk_dossiers import TkDossiersNormalizePipeline

logger = get_logger(__name__)


def _parse_since(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    value = value.strip()
    if value.endswith("d") and value[:-1].isdigit():
        days = int(value[:-1])
        return dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    try:
        parsed = dt.datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed
    except ValueError as exc:
        raise ValueError(f"Cannot parse --since value '{value}'.") from exc


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Normalize raw TK dossier records into graph nodes and edges."
    )
    parser.add_argument(
        "--since",
        default=None,
        help="Only process raw records fetched since this date (ISO 8601 or '7d').",
    )
    args = parser.parse_args(argv)

    try:
        since = _parse_since(args.since)
    except ValueError as exc:
        parser.error(str(exc))
        return

    store = ArangoStore()
    pipeline = TkDossiersNormalizePipeline(store=store)
    try:
        pipeline.run(since=since)
    except Exception as exc:
        logger.error("TK dossiers normalization failed: %s", exc)
        sys.exit(1)
    logger.info("TK dossiers normalization complete.")


if __name__ == "__main__":
    main()
