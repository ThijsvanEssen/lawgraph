"""The reads of ``semantic tk-dossier-eu``: every dossier's title with the EU acts the laws it
legislated implement, and the COM documents the graph holds."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_DOSSIERS,
    COLLECTION_EDGES,
    COLLECTION_INSTRUMENTS,
    RELATION_IMPLEMENTS,
    RELATION_LEGISLATED_IN,
)
from lawgraph.db.counting import Store


def legislated_implements(dossier: str) -> str:
    """SQL ``FROM … WHERE``: the ``IMPLEMENTS`` edges (``m``) from an instrument (``s``)
    ``LEGISLATED_IN`` the dossier whose id is the SQL *dossier*, to the EU act ``eu``. Binds
    ``implements`` and ``legislated_in``."""
    return f"""
        FROM {COLLECTION_EDGES} l
        JOIN {COLLECTION_INSTRUMENTS} s ON s.id = l.from_id
        JOIN {COLLECTION_EDGES} m ON m.from_id = s.id AND m.relation = %(implements)s
        JOIN {COLLECTION_INSTRUMENTS} eu ON eu.id = m.to_id
        WHERE l.to_id = {dossier} AND l.relation = %(legislated_in)s
          AND l.from_collection = '{COLLECTION_INSTRUMENTS}'"""


# Per dossier the EU acts the instruments LEGISLATED_IN it implement, each with the bases of
# those IMPLEMENTS edges (``meta.bases``), as ``[celex, bases]``.
_DOSSIERS_SQL = f"""
SELECT ds.id, ds.key, lg_str(ds.pj_title) AS title,
       ds.props -> 'eu_ref' AS eu_ref, ds.props -> 'implements' AS implements,
       (
           SELECT json_agg(json_build_array(eu.celex, m.doc -> 'meta' -> 'bases')
                           ORDER BY eu.celex ASC NULLS FIRST, m.key ASC)
           {legislated_implements("ds.id")}
             AND eu.celex IS NOT NULL
       ) AS legislated
FROM {COLLECTION_DOSSIERS} ds
ORDER BY ds.key
"""


def dossiers_with_eu(store: Store) -> Iterator[dict[str, Any]]:
    """``{id, key, title, eu_ref, implements, legislated}`` of every dossier: what it stores
    of the EU, and ``legislated`` the ``[celex, bases]`` of the ``IMPLEMENTS`` of the
    instruments ``LEGISLATED_IN`` it (null for none)."""
    return store.query(
        _DOSSIERS_SQL,
        {
            "implements": RELATION_IMPLEMENTS,
            "legislated_in": RELATION_LEGISLATED_IN,
        },
    )


def celex_in_graph(store: Store, candidates: list[str]) -> set[str]:
    """Those of the CELEX numbers *candidates* an instrument of the graph has."""
    if not candidates:
        return set()
    rows = store.query(
        f"SELECT DISTINCT celex FROM {COLLECTION_INSTRUMENTS}"
        " WHERE celex = ANY(%(candidates)s::text[])",
        {"candidates": candidates},
    )
    return set(rows)
