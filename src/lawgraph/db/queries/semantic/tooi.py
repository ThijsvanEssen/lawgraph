"""The reads of the semantic phase for the ministries (``semantic tooi-ministries``): the
nodes that name a ministry, and the posts held under one."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_COMMITMENTS,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_MEMBERS,
    SOURCE_STAATSBLAD,
    SOURCE_STAATSCOURANT,
)
from lawgraph.db.counting import Store
from lawgraph.db.queries._json_sql import array_or_empty

# Each table keeps its ``ministry`` as a derived column, the dossiers and commitments with
# an index on it, the instruments too.
# A publication of the Staatsblad or the Staatscourant names its own: each of its
# ``ministries`` (``core.publication_creators``), read by the index on ``source``.
_LED_SQL = " UNION ALL ".join(
    [
        *(
            f"SELECT id, ministry FROM {table} WHERE ministry IS NOT NULL"
            for table in (
                COLLECTION_INSTRUMENTS,
                COLLECTION_DOSSIERS,
                COLLECTION_COMMITMENTS,
            )
        ),
        f"""SELECT d.id, m.ministry
        FROM {COLLECTION_DOCUMENTS} d
        CROSS JOIN LATERAL json_array_elements_text(
            {array_or_empty("d.props -> 'ministries'")}
        ) AS m(ministry)
        WHERE d.source IN ('{SOURCE_STAATSBLAD}', '{SOURCE_STAATSCOURANT}')""",
    ]
)

_POSTS_SQL = f"""
SELECT m.id, f.post
FROM {COLLECTION_MEMBERS} m
CROSS JOIN LATERAL json_array_elements(m.props -> 'government_functions')
    WITH ORDINALITY AS f(post, n)
WHERE cardinality(m.cabinet_keys) > 0
  AND json_typeof(m.props -> 'government_functions') = 'array'
  AND lg_str(f.post -> 'ministry') IS NOT NULL
ORDER BY m.id, f.n
"""


def ministry_leads(store: Store) -> Iterator[dict[str, Any]]:
    """``{id, ministry}`` of every instrument, dossier and commitment that names a
    ministry (its ``ministry``, a key of ``core.ministries``), and of every publication of
    the Staatsblad and the Staatscourant per ministry it names (its ``ministries``)."""
    return store.query(_LED_SQL)


def ministry_posts(store: Store) -> Iterator[dict[str, Any]]:
    """``{id, post}``: every post of a member's ``government_functions`` that names a
    ministry, the member by id, in the order of the member and its posts."""
    return store.query(_POSTS_SQL)
