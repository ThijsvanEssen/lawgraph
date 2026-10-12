"""The regulations issued under an article: ``BASED_ON`` edges into it, with the articles of
each regulation that refer to it.

``semantic bwb-grondslagen`` writes ``Instrument --BASED_ON--> Article`` from the "Gelet op"
paragraph of a regulation, with the text of that reference in ``meta.text`` ("16, eerste en
zevende lid"). The articles of such a regulation that name the article ("als bedoeld in artikel
16, eerste lid, van de wet") are its ``REFERS_TO`` edges into it.
"""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_EDGES,
    COLLECTION_INSTRUMENT_VERSIONS,
    COLLECTION_INSTRUMENTS,
    RELATION_BASED_ON,
    RELATION_REFERS_TO,
)
from lawgraph.db import GraphStore

# One row per regulation: the regulation, the meta of its edge (one per regulation: the
# lowest key, as the edge writer keys one edge per pair) and the articles of the regulation
# that refer to the article, in the order of the regulation. Both passes read the edges of
# the article by the ``(to_id, relation, from_collection)`` index; only the articles of the
# regulations found are read.
_DELEGATED_SQL = f"""
WITH based AS (
    SELECT DISTINCT ON (e.from_id) e.from_id, e.doc -> 'meta' AS meta
    FROM {COLLECTION_EDGES} e
    WHERE e.to_id = %(article_id)s AND e.relation = %(based_on)s
      AND e.from_collection = '{COLLECTION_INSTRUMENTS}'
    ORDER BY e.from_id, e.key
),
regulations AS (
    SELECT i.id, i.key, i.type, i.labels, i.props, i.bwb_id, b.meta
    FROM based b JOIN {COLLECTION_INSTRUMENTS} i ON i.id = b.from_id
),
referring AS (
    SELECT a.bwb_id, json_agg(json_build_object(
        'id', a.id,
        'key', a.key,
        'article_number', a.article_number,
        'display_name', a.props -> 'display_name',
        'meta', r.doc -> 'meta'
    ) ORDER BY a.position NULLS LAST, a.key) AS articles
    FROM {COLLECTION_EDGES} r
    JOIN {COLLECTION_ARTICLES} a ON a.id = r.from_id
    WHERE r.to_id = %(article_id)s AND r.relation = %(refers_to)s
      AND r.from_collection = '{COLLECTION_ARTICLES}'
      AND a.repealed IS NOT TRUE
      AND a.bwb_id IN (SELECT g.bwb_id FROM regulations g)
    GROUP BY a.bwb_id
)
SELECT json_build_object('_key', g.key, '_id', g.id, 'type', g.type,
                         'labels', to_json(g.labels), 'props', g.props) AS instrument,
       g.meta,
       coalesce(f.articles, '[]'::json) AS articles
FROM regulations g
LEFT JOIN referring f ON f.bwb_id = g.bwb_id
ORDER BY g.key
"""


def get_delegated_regulations(
    store: GraphStore, article_id: str
) -> list[dict[str, Any]]:
    """The regulations ``BASED_ON`` the article, by key: ``{instrument, meta, articles}``
    with ``articles`` the articles of the regulation that refer to it (``id``, ``key``,
    ``article_number``, ``display_name``, ``meta`` of the reference). One query."""
    return list(
        store.query(
            _DELEGATED_SQL,
            {
                "article_id": article_id,
                "based_on": RELATION_BASED_ON,
                "refers_to": RELATION_REFERS_TO,
            },
        )
    )


# One row per regulation issued under any article of a law: the regulation and the articles
# of the law its preamble names, each with the meta of its edge (one per pair: the lowest
# key), in the order of the law. The articles of the law by their ``(bwb_id, …)`` index,
# their edges by the ``(to_id, relation, from_collection)`` index: one probe per article,
# in the query. A regulation whose versions are all closed (none ``current``: repealed) is
# left out; one without versions is kept. One probe of the ``(bwb_id, current)`` index.
_DELEGATED_BY_LAW_SQL = f"""
WITH based AS (
    SELECT DISTINCT ON (e.from_id, a.id)
           e.from_id, a.id, a.key, a.article_number, a.position,
           a.props -> 'display_name' AS display_name, e.doc -> 'meta' AS meta
    FROM {COLLECTION_ARTICLES} a
    JOIN {COLLECTION_EDGES} e
      ON e.to_id = a.id AND e.relation = %(based_on)s
     AND e.from_collection = '{COLLECTION_INSTRUMENTS}'
    WHERE a.bwb_id = %(bwb)s
    ORDER BY e.from_id, a.id, e.key
),
grouped AS (
    SELECT b.from_id, json_agg(json_build_object(
        'id', b.id,
        'key', b.key,
        'article_number', b.article_number,
        'display_name', b.display_name,
        'meta', b.meta
    ) ORDER BY b.position NULLS LAST, b.key) AS articles
    FROM based b
    GROUP BY b.from_id
)
SELECT json_build_object('_key', i.key, '_id', i.id, 'type', i.type,
                         'labels', to_json(i.labels), 'props', i.props) AS instrument,
       g.articles
FROM grouped g
JOIN {COLLECTION_INSTRUMENTS} i ON i.id = g.from_id
WHERE (
    SELECT bool_or(v.current IS TRUE) FROM {COLLECTION_INSTRUMENT_VERSIONS} v
    WHERE v.bwb_id = i.bwb_id
) IS NOT FALSE
"""


def get_delegated_by_law(store: GraphStore, bwb_id: str) -> list[dict[str, Any]]:
    """The regulations ``BASED_ON`` any article of the law *bwb_id*, in no order:
    ``{instrument, articles}`` with ``articles`` the articles of the law its preamble names
    (``id``, ``key``, ``article_number``, ``display_name``, ``meta`` of the edge), in the
    order of the law. Repealed regulations (every version closed) are left out. One query."""
    return list(
        store.query(
            _DELEGATED_BY_LAW_SQL,
            {"bwb": bwb_id.upper(), "based_on": RELATION_BASED_ON},
        )
    )
