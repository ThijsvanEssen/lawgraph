"""Queries of the pipelines of eerstekamer.nl that read the graph."""

from __future__ import annotations

from collections.abc import Iterator

from lawgraph.config.constants import COLLECTION_COMMITTEES, COLLECTION_DECISIONS
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


def ek_committee_keys(store: Store) -> dict[str, str]:
    """The abbreviation of every committee of the Eerste Kamer (``FIN``) -> its key."""
    return {
        str(row["abbreviation"]): str(row["key"])
        for row in store.query(
            f"""
            SELECT c.key, lg_str(c.props -> 'abbreviation') AS abbreviation
            FROM {COLLECTION_COMMITTEES} c
            WHERE lg_str(c.props -> 'chamber') = 'EK'
              AND lg_str(c.props -> 'abbreviation') IS NOT NULL
            ORDER BY c.key ASC NULLS FIRST
            """
        )
    }
