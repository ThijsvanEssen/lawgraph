"""CLI: retrieve parliamentary dossier entities from the TK OData API.

Usage:
  lawgraph-retrieve-tk-dossiers               # full refresh of all entities
  lawgraph-retrieve-tk-dossiers --since 7d    # only records modified in last 7 days
  lawgraph-retrieve-tk-dossiers --skip-personen  # skip slow Persoon fetch
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys

from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger, setup_logging
from lawgraph.pipelines.retrieve.tk_dossiers import TkDossiersRetrievePipeline

logger = get_logger(__name__)


def _parse_since(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    value = value.strip()
    # Shorthand: "7d", "30d"
    if value.endswith("d") and value[:-1].isdigit():
        days = int(value[:-1])
        return dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    # ISO 8601
    try:
        parsed = dt.datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed
    except ValueError as exc:
        raise ValueError(
            f"Cannot parse --since value '{value}'. Use ISO 8601 or e.g. '7d'."
        ) from exc


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Retrieve parliamentary dossier entities from the TK OData API."
    )
    parser.add_argument(
        "--since",
        default=None,
        help="Only fetch records modified since this date (ISO 8601 or '7d', '30d').",
    )
    parser.add_argument(
        "--skip-personen",
        action="store_true",
        help="Skip Persoon fetch (slow; only needed for full refreshes).",
    )
    parser.add_argument(
        "--skip-stemmingen",
        action="store_true",
        help="Skip Stemming fetch entirely.",
    )
    parser.add_argument(
        "--stemmingen-since",
        default=None,
        metavar="DATE",
        help=(
            "Only fetch Stemming records modified since this date. "
            "Overrides --since for stemmingen only. "
            "Use e.g. '730d' to limit to the last 2 years."
        ),
    )
    parser.add_argument(
        "--skip-documents",
        action="store_true",
        help="Skip Document (Kamerstuk) fetch.",
    )
    parser.add_argument(
        "--documents-since",
        default=None,
        metavar="DATE",
        help=(
            "Only fetch Document records modified since this date. "
            "Overrides --since for documents only. "
            "Recommended: '730d' or '365d' — a full fetch is ~400K+ records."
        ),
    )
    parser.add_argument(
        "--dossier-nummer",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Targeted backfill: fetch only Documents linked to this "
            "Kamerstukdossier nummer, ignoring date filters and skipping all "
            "other entity types. Use to fill gaps for dormant dossiers whose "
            "stukken predate the documents-since window."
        ),
    )
    args = parser.parse_args(argv)

    try:
        since = _parse_since(args.since)
        stemmingen_since = _parse_since(args.stemmingen_since)
        documents_since = _parse_since(args.documents_since)
    except ValueError as exc:
        parser.error(str(exc))
        return

    setup_logging()
    store = ArangoStore()
    pipeline = TkDossiersRetrievePipeline(store=store)
    result = pipeline.run(
        since=since,
        stemmingen_since=stemmingen_since,
        documents_since=documents_since,
        skip_personen=args.skip_personen,
        skip_stemmingen=args.skip_stemmingen,
        skip_documents=args.skip_documents,
        dossier_nummer=args.dossier_nummer,
    )
    logger.info(result.summary())
    if result.errors:
        for err in result.errors:
            logger.error(err)
        sys.exit(1)


if __name__ == "__main__":
    main()
