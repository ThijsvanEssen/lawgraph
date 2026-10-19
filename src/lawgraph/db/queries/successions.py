"""The reads of old law to new law: the stored transposition tables, and the laws a table
names with their articles (``semantic tk-transposition-tables``, ``lawgraph
succession-gaps``)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_INSTRUMENTS,
    RAW_KIND_TK_TRANSPOSITION_TABLE,
    RELATION_ESTABLISHES,
    RELATION_LEGISLATED_IN,
    RELATION_PART_OF,
    SOURCE_TK,
)
from lawgraph.db.counting import Store
from lawgraph.db.queries import raw as raw_queries
from lawgraph.db.queries._json_sql import array_or_empty

# The laws whose articles a publication made in the dossier enacted (``ESTABLISHES``): a
# law of the Staatsblad or of the BWB, with its citation title.
_LAWS_OF_DOSSIER = f"""
SELECT DISTINCT i.id, i.citation_title
FROM edges l
JOIN edges est ON est.from_id = l.from_id AND est.relation = '{RELATION_ESTABLISHES}'
JOIN edges p ON p.from_id = est.to_id AND p.relation = '{RELATION_PART_OF}'
  AND p.to_collection = '{COLLECTION_INSTRUMENTS}'
JOIN {COLLECTION_INSTRUMENTS} i ON i.id = p.to_id
WHERE l.to_id = %(dossier)s AND l.relation = '{RELATION_LEGISLATED_IN}'
ORDER BY i.id
"""

# The laws of the BWB of a citation title, as written in any case.
_BWB_LAWS_NAMED = f"""
SELECT id FROM {COLLECTION_INSTRUMENTS}
WHERE bwb_id IS NOT NULL AND stub IS DISTINCT FROM TRUE
  AND lower(citation_title) = lower(%(name)s)
ORDER BY id
"""

# The articles of a law that are no stub and have a number, in the order of the law, each
# with the numbers of its leden (``props.parts`` of kind ``lid``).
_LAW_ARTICLES = f"""
SELECT a.id, a.article_number AS number, coalesce(a.repealed, false) AS repealed,
       ARRAY(
           SELECT p ->> 'number'
           FROM json_array_elements({array_or_empty("a.props -> 'parts'")}) p
           WHERE p ->> 'kind' = 'lid' AND p ->> 'number' IS NOT NULL
       ) AS leden
FROM edges e
JOIN {COLLECTION_ARTICLES} a ON a.id = e.from_id
WHERE e.to_id = %(law)s AND e.relation = '{RELATION_PART_OF}'
  AND e.from_collection = '{COLLECTION_ARTICLES}'
  AND a.article_number IS NOT NULL AND a.stub IS DISTINCT FROM TRUE
ORDER BY a.position NULLS LAST, a.id
"""


def laws_of_dossier(store: Store, dossier_id: str) -> list[dict[str, Any]]:
    """``{id, citation_title}`` of each law a publication of the dossier enacted."""
    return list(store.query(_LAWS_OF_DOSSIER, {"dossier": dossier_id}))


def bwb_laws_named(store: Store, name: str) -> list[str]:
    """The ids of the laws of the BWB whose citation title is *name*."""
    return [str(row) for row in store.query(_BWB_LAWS_NAMED, {"name": name})]


def law_articles(store: Store, law_id: str) -> list[dict[str, Any]]:
    """``{id, number, repealed, leden}`` of each numbered article of the law."""
    return list(store.query(_LAW_ARTICLES, {"law": law_id}))


def transposition_tables(store: Store) -> Iterator[dict[str, Any]]:
    """Every stored transposition table, with its payload."""
    rows = raw_queries.iter_raw_records(
        store,
        source=SOURCE_TK,
        kinds=[RAW_KIND_TK_TRANSPOSITION_TABLE],
        since_iso=None,
        batch_size=1,
    )
    return store.with_payloads(rows)
