"""CLI: retrieve parliamentary dossier entities from the TK OData API.

Usage:
  lawgraph-retrieve-tk-dossiers               # full refresh of all entities
  lawgraph-retrieve-tk-dossiers --since 7d    # only records modified in last 7 days
  lawgraph-retrieve-tk-dossiers --skip-personen  # skip slow Persoon fetch
"""

from __future__ import annotations

import argparse
import datetime as dt

from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger
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


def main() -> None:
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
    args = parser.parse_args()

    try:
        since = _parse_since(args.since)
    except ValueError as exc:
        parser.error(str(exc))
        return

    store = ArangoStore()
    pipeline = TkDossiersRetrievePipeline(store=store)
    result = pipeline.run(since=since, skip_personen=args.skip_personen)
    print(result.summary())
    if result.errors:
        for err in result.errors:
            print(f"  ERROR: {err}")


if __name__ == "__main__":
    main()
