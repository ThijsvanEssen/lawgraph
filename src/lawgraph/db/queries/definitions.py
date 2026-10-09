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
from lawgraph.core.bwb_definitions import TermMatcher, definition_ref
from lawgraph.core.models import make_node_key
from lawgraph.db.counting import Store
from lawgraph.db.version_cache import cached


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


def term_matcher(store: Any, instrument_id: str) -> TermMatcher:
    """The compiled matcher of the defined terms of *instrument_id*, kept per data version
    (``cached``): an article of the Wft does not compile its hundreds of terms again."""
    return cached(
        store,
        ("term_matcher", instrument_id),
        lambda: TermMatcher(definitions_of(store, instrument_id)),
    )


def article_terms(
    store: Any,
    instrument_id: str,
    article_props: dict[str, Any],
    citations: list[tuple[int, int, str | None]],
) -> tuple[list[dict[str, Any]], dict[int, str], list[dict[str, Any]]]:
    """The defined terms of an article: ``(term spans, definition_ref per citation index,
    the definitions they name)``.

    *citations* are the ``(start, end, cited BWB id)`` of its citation spans. A term inside
    a citation is no span of its own ("de Algemene wet bestuursrecht" holds "wet"); when its
    definition is the regulation cited ("artikel 11 van de wet", the Zorgverzekeringswet),
    the citation names that definition."""
    text = str(article_props.get("text") or "")
    path = str(article_props.get("path") or "")
    spans: list[dict[str, Any]] = []
    refs: dict[int, str] = {}
    used: dict[str, dict[str, Any]] = {}
    for start, end, definition in term_matcher(store, instrument_id).find(text, path):
        inside = next(
            (i for i, (s, e, _) in enumerate(citations) if s < end and start < e),
            None,
        )
        ref = definition_ref(definition)
        if inside is None:
            spans.append(
                {
                    "start": start,
                    "end": end,
                    "term": definition["term"],
                    "definition_ref": ref,
                }
            )
        elif (
            definition.get("refers_to")
            and definition["refers_to"] == citations[inside][2]
        ):
            refs.setdefault(inside, ref)
        else:
            continue
        used.setdefault(ref, definition)
    return spans, refs, list(used.values())
