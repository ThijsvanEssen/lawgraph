"""Queries of the pipelines of eerstekamer.nl that read the graph."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_COMMITTEES,
    COLLECTION_DECISIONS,
    COLLECTION_DOCUMENTS,
    COLLECTION_FACTIONS,
)
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


def ek_factions(store: Store) -> Iterator[dict[str, Any]]:
    """``{id, abbreviation, seats, observed_from, observed_until}`` of every faction of the
    Eerste Kamer, by key: what the list of votes names a faction by, and when it was seen
    with how many seats."""
    return store.query(
        f"""
        SELECT f.id, lg_str(f.props -> 'abbreviation') AS abbreviation,
               lg_num(f.props -> 'seats')::int AS seats,
               lg_str(f.props -> 'observed_from') AS observed_from,
               lg_str(f.props -> 'observed_until') AS observed_until
        FROM {COLLECTION_FACTIONS} f
        WHERE lg_str(f.props -> 'chamber') = 'EK'
          AND lg_str(f.props -> 'abbreviation') IS NOT NULL
        ORDER BY f.key ASC NULLS FIRST
        """
    )


def ek_vote_keys_on(store: Store, days: list[str]) -> list[str]:
    """The keys of the decisions ``normalize eerstekamer-votes`` made of the votes of
    *days* (YYYY-MM-DD): the votes of the Eerste Kamer, keyed ``ek_<day>_…``."""
    return list(
        store.query(
            f"""
            SELECT d.key FROM {COLLECTION_DECISIONS} d
            WHERE d.date = ANY(%(days)s::text[])
              AND lg_str(d.props -> 'chamber') = 'EK'
              AND starts_with(d.key, 'ek_')
            ORDER BY d.key
            """,
            {"days": days},
        )
    )


def ek_papers_by_letter(store: Store, numbers: list[str]) -> dict[tuple[str, str], str]:
    """``(dossier label, letter) -> id`` of the Kamerstukken of the Eerste Kamer of the
    dossiers *numbers* (their number without a suffix: ``37020``), as ``normalize
    eerstekamer`` keeps them (``Kamerstuk I 37020, M``): a motion is one of them."""
    found: dict[tuple[str, str], str] = {}
    for row in store.query(
        f"""
        SELECT d.id, lg_str(d.props -> 'number') AS letter,
               lg_text_array(d.props -> 'dossier_numbers') AS labels
        FROM {COLLECTION_DOCUMENTS} d
        WHERE d.dossier_number = ANY(%(numbers)s::text[])
          AND d.labels @> ARRAY['EK']
        ORDER BY d.id
        """,
        {"numbers": numbers},
    ):
        for label in row["labels"] or []:
            if row["letter"]:
                found.setdefault((label, row["letter"]), row["id"])
    return found
