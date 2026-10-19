"""``lg_instrument_definitions``: the definitions each regulation gives itself
(``core.bwb_definitions``), kept by ``semantic bwb-definitions``; and those a regulation
takes from the regulations it is issued under (``BASED_ON``, two levels)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_EDGES,
    COLLECTION_INSTRUMENTS,
    RAW_KIND_BWB_TOESTAND,
    RELATION_BASED_ON,
    SOURCE_BWB,
)
from lawgraph.core.bwb_definitions import TermMatcher, definition_ref, inherited
from lawgraph.core.models import make_node_key, node_id
from lawgraph.db.counting import Store
from lawgraph.db.schema import DEFINITIONS_TABLE
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
    replacing what was kept; a regulation without any loses its row. A row that holds them
    already is left, so a run that changes nothing leaves the data version."""
    if not found:
        return
    rows = [
        {
            "instrument_id": node_id(COLLECTION_INSTRUMENTS, make_node_key(bwb_id)),
            "bwb_id": bwb_id,
            "definitions": definitions,
        }
        for bwb_id, definitions in found.items()
    ]
    store.execute_together(
        [
            (
                f"""
                INSERT INTO {DEFINITIONS_TABLE} (instrument_id, bwb_id, definitions)
                SELECT r.instrument_id, r.bwb_id, r.definitions
                FROM json_to_recordset(%(rows)s::json)
                     AS r(instrument_id text, bwb_id text, definitions json)
                WHERE json_array_length(r.definitions) > 0
                ON CONFLICT (instrument_id) DO UPDATE SET
                    bwb_id = EXCLUDED.bwb_id, definitions = EXCLUDED.definitions
                WHERE ({DEFINITIONS_TABLE}.bwb_id,
                       {DEFINITIONS_TABLE}.definitions::text)
                      IS DISTINCT FROM (EXCLUDED.bwb_id, EXCLUDED.definitions::text)
                """,
                {"rows": json.dumps(rows)},
            ),
            (
                f"""
                DELETE FROM {DEFINITIONS_TABLE}
                WHERE instrument_id = ANY(%(empty)s::text[])
                """,
                {"empty": [r["instrument_id"] for r in rows if not r["definitions"]]},
            ),
        ]
    )


def remove_definitions_except(
    store: Store, seen: list[str], *, after: str | None, upto: str | None
) -> int:
    """Remove the rows of the regulations past *after* up to *upto* (both by BWB id; None:
    no bound) that are not in *seen*: a run read every stored toestand of that range, so
    one not read is no longer stored. How many went."""
    return len(
        store.execute(
            f"""
            DELETE FROM {DEFINITIONS_TABLE} d
            WHERE (%(after)s::text IS NULL OR d.bwb_id > %(after)s)
              AND (%(upto)s::text IS NULL OR d.bwb_id <= %(upto)s)
              AND NOT EXISTS (SELECT 1 FROM unnest(%(seen)s::text[]) s WHERE s = d.bwb_id)
            RETURNING 1
            """,
            {"seen": seen, "after": after, "upto": upto},
        )
    )


def definitions_of(store: Store, instrument_id: str) -> list[dict[str, Any]]:
    """The definitions kept for the instrument *instrument_id*, in the order of its text."""
    rows = store.query(
        f"SELECT definitions FROM {DEFINITIONS_TABLE} WHERE instrument_id = %(id)s",
        {"id": instrument_id},
    )
    found = next(iter(rows), None)
    return list(found) if isinstance(found, list) else []


# The regulations a regulation is issued under that give definitions: level 1 those whose
# articles its preamble names (its ``BASED_ON`` edges, by the ``edges_from_cover`` index),
# level 2 those of each of them; each with the paths of the articles named (where in the
# law its basis stands) and its definitions. A regulation of both levels counts at the
# first. A handful of edges and rows by their keys: the definitions of each regulation
# found by its key, not the table of definitions walked for them.
_BASES_SQL = f"""
WITH first AS (
    SELECT a.bwb_id, array_agg(DISTINCT coalesce(a.props ->> 'path', '')) AS paths
    FROM {COLLECTION_EDGES} e JOIN {COLLECTION_ARTICLES} a ON a.id = e.to_id
    WHERE e.from_id = %(id)s AND e.relation = %(based_on)s
      AND e.to_collection = '{COLLECTION_ARTICLES}'
    GROUP BY a.bwb_id
),
second AS (
    SELECT a.bwb_id, array_agg(DISTINCT coalesce(a.props ->> 'path', '')) AS paths
    FROM first f
    JOIN {COLLECTION_INSTRUMENTS} i ON i.bwb_id = f.bwb_id
    JOIN {COLLECTION_EDGES} e ON e.from_id = i.id AND e.relation = %(based_on)s
     AND e.to_collection = '{COLLECTION_ARTICLES}'
    JOIN {COLLECTION_ARTICLES} a ON a.id = e.to_id
    WHERE a.bwb_id NOT IN (SELECT bwb_id FROM first)
    GROUP BY a.bwb_id
),
bases AS (
    SELECT 1 AS level, bwb_id, paths FROM first
    UNION ALL
    SELECT 2, bwb_id, paths FROM second
),
given AS (
    SELECT b.level, b.bwb_id, b.paths, i.key,
           i.props -> 'citation_title' AS citation_title,
           i.props -> 'short_title' AS short_title,
           i.props -> 'abbreviation' AS abbreviation,
           (SELECT d.definitions FROM {DEFINITIONS_TABLE} d
            WHERE d.instrument_id = i.id) AS definitions
    FROM bases b JOIN {COLLECTION_INSTRUMENTS} i ON i.bwb_id = b.bwb_id
    WHERE i.id <> %(id)s
)
SELECT json_build_object(
    'level', g.level,
    'paths', to_json(g.paths),
    'definitions', g.definitions,
    'given_by', json_build_object(
        'key', g.key,
        'bwb_id', g.bwb_id,
        'citation_title', g.citation_title,
        'short_title', g.short_title,
        'abbreviation', g.abbreviation
    )
)
FROM given g
WHERE g.definitions IS NOT NULL
ORDER BY g.level ASC NULLS LAST, g.bwb_id ASC NULLS LAST
"""


def taken_definitions(store: Store, instrument_id: str) -> list[dict[str, Any]]:
    """The definitions *instrument_id* takes from the regulations it is issued under
    (``core.bwb_definitions.inherited``), each with ``given_by``. One query."""
    return inherited(
        list(
            store.query(
                _BASES_SQL, {"id": instrument_id, "based_on": RELATION_BASED_ON}
            )
        )
    )


def term_matcher(store: Store, instrument_id: str) -> TermMatcher:
    """The compiled matcher of the defined terms of *instrument_id*, its own and those it
    takes, kept per data version (``cached``): an article of the Wft does not compile its
    hundreds of terms again."""
    return cached(
        store,
        ("term_matcher", instrument_id),
        lambda: TermMatcher(
            definitions_of(store, instrument_id),
            taken_definitions(store, instrument_id),
        ),
    )


def article_terms(
    store: Store,
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
