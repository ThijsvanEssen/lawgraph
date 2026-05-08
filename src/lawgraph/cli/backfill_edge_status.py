"""CLI: backfill status=canoniek on all edges that lack the field.

Run once after migrating to the unified-edge + status model.  Safe to re-run
— edges that already have a status are untouched.
"""

from __future__ import annotations

import argparse

from lawgraph.config.settings import COLLECTION_EDGES, EDGE_STATUS_CANONIEK
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger

logger = get_logger(__name__)


def _backfill(store: ArangoStore, *, dry_run: bool = False) -> int:
    """Set status=canoniek on every edge that has no status field. Returns count."""
    count_aql = f"""
    FOR e IN {COLLECTION_EDGES}
        FILTER e.status == null
        COLLECT WITH COUNT INTO n
    RETURN n
    """
    rows = list(store.query(count_aql))
    total = rows[0] if rows else 0
    logger.info("Found %d edges without status field.", total)

    if total == 0 or dry_run:
        if dry_run:
            logger.info("[dry-run] Would backfill %d edges.", total)
        return total

    update_aql = f"""
    FOR e IN {COLLECTION_EDGES}
        FILTER e.status == null
        UPDATE e WITH {{ status: @status }} IN {COLLECTION_EDGES}
    RETURN 1
    """
    updated = list(store.query(update_aql, bind_vars={"status": EDGE_STATUS_CANONIEK}))
    count = len(updated)
    logger.info("Backfilled status=%s on %d edges.", EDGE_STATUS_CANONIEK, count)
    return count


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill status=canoniek on all edges that lack the field."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count edges but don't write any changes.",
    )
    args = parser.parse_args()

    store = ArangoStore()
    count = _backfill(store, dry_run=args.dry_run)
    action = "Would backfill" if args.dry_run else "Backfilled"
    print(f"{action} {count} edges.")


if __name__ == "__main__":
    main()
