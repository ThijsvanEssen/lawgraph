"""``lg_instrument_definitions``: the definitions each regulation gives itself
(``core.bwb_definitions``), kept by ``semantic bwb-definitions``."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_INSTRUMENTS,
    RAW_KIND_BWB_TOESTAND,
    SOURCE_BWB,
)
from lawgraph.core.models import make_node_key
from lawgraph.db.counting import Store


def toestanden(
    store: Store, *, since_iso: str | None, after: str | None, limit: int | None
) -> Iterator[dict[str, Any]]:
    """``{bwb_id, payload_ref}`` of the stored toestanden, by BWB id: those fetched at or
    after *since_iso*, past the BWB id *after*, at most *limit*; fifty to a cursor batch."""
    return store.query(
        """
        SELECT external_id AS bwb_id, doc -> 'payload_ref' AS payload_ref FROM raw_sources
        WHERE source = %(source)s AND kind = %(kind)s AND external_id IS NOT NULL
          AND (%(since)s::text IS NULL OR fetched_at >= %(since)s)
          AND (%(after)s::text IS NULL OR external_id > %(after)s)
        ORDER BY external_id ASC NULLS FIRST
        LIMIT %(limit)s
        """,
        {
            "source": SOURCE_BWB,
            "kind": RAW_KIND_BWB_TOESTAND,
            "since": since_iso,
            "after": after,
            "limit": limit,
        },
        batch_size=50,
    )


def keep_definitions(store: Store, found: dict[str, list[dict[str, Any]]]) -> None:
    """Write the definitions of each regulation of *found* (BWB id -> its definitions),
    replacing what was kept; a regulation without any loses its row."""
    if not found:
        return
    rows = [
        {
            "instrument_id": f"{COLLECTION_INSTRUMENTS}/{make_node_key(bwb_id)}",
            "bwb_id": bwb_id,
            "definitions": definitions,
        }
        for bwb_id, definitions in found.items()
    ]
    store.execute_together(
        [
            (
                """
                INSERT INTO lg_instrument_definitions (instrument_id, bwb_id, definitions)
                SELECT r.instrument_id, r.bwb_id, r.definitions
                FROM json_to_recordset(%(rows)s::json)
                     AS r(instrument_id text, bwb_id text, definitions json)
                WHERE json_array_length(r.definitions) > 0
                ON CONFLICT (instrument_id) DO UPDATE SET
                    bwb_id = EXCLUDED.bwb_id, definitions = EXCLUDED.definitions
                """,
                {"rows": json.dumps(rows)},
            ),
            (
                """
                DELETE FROM lg_instrument_definitions
                WHERE instrument_id = ANY(%(empty)s::text[])
                """,
                {"empty": [r["instrument_id"] for r in rows if not r["definitions"]]},
            ),
        ]
    )


def definitions_of(store: Store, instrument_id: str) -> list[dict[str, Any]]:
    """The definitions kept for the instrument *instrument_id*, in the order of its text."""
    rows = store.query(
        "SELECT definitions FROM lg_instrument_definitions WHERE instrument_id = %(id)s",
        {"id": instrument_id},
    )
    found = next(iter(rows), None)
    return list(found) if isinstance(found, list) else []
