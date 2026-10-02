"""Queries of the pipelines of eerstekamer.nl that read the graph."""

from __future__ import annotations

from collections.abc import Iterator

from lawgraph.config.constants import COLLECTION_DECISIONS
from lawgraph.db.counting import Store


def voted_bill_urls(store: Store, since: str | None) -> Iterator[str]:
    """The pages of the bills the list of votes of the Eerste Kamer named (``bill_url`` of
    its decisions), of votes on or after *since* (every one without)."""
    return store.query(
        f"""
        SELECT DISTINCT lg_str(d.props -> 'bill_url') AS url
        FROM {COLLECTION_DECISIONS} d
        WHERE lg_str(d.props -> 'bill_url') IS NOT NULL
          AND (%(since)s::text IS NULL OR d.date >= %(since)s::text)
        ORDER BY 1 ASC NULLS FIRST
        """,
        {"since": since},
    )
