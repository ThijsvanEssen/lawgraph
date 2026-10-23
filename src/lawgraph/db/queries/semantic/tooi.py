"""The reads of the semantic phase for the ministries (``semantic tooi-ministries``): the
nodes that name a ministry, and the posts held under one."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_COMMITMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_MEMBERS,
)
from lawgraph.db.counting import Store

# Each table keeps its ``ministry`` as a derived column, the dossiers and commitments with
# an index on it, the instruments too.
_LED_SQL = " UNION ALL ".join(
    f"SELECT id, ministry FROM {table} WHERE ministry IS NOT NULL"
    for table in (COLLECTION_INSTRUMENTS, COLLECTION_DOSSIERS, COLLECTION_COMMITMENTS)
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
    ministry (its ``ministry``, a key of ``core.ministries``)."""
    return store.query(_LED_SQL)


def ministry_posts(store: Store) -> Iterator[dict[str, Any]]:
    """``{id, post}``: every post of a member's ``government_functions`` that names a
    ministry, the member by id, in the order of the member and its posts."""
    return store.query(_POSTS_SQL)
