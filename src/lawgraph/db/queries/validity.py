"""What ``core.validity`` reads beyond the props of a node: the end of an article (its newest
version), the laws that take the place of a law (``TRANSPOSED_TO``), and the day the data of
a source stands on."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLE_VERSIONS,
    COLLECTION_ARTICLES,
    COLLECTION_INSTRUMENTS,
    RELATION_PART_OF,
    RELATION_TRANSPOSED_TO,
)
from lawgraph.core.time import dutch_day
from lawgraph.db import GraphStore
from lawgraph.db.queries.stats import cached_data_as_of

_NEWEST_VERSION = f"""(
    SELECT v.valid_until FROM {COLLECTION_ARTICLE_VERSIONS} v
    WHERE v.bwb_id = {{alias}}.bwb_id AND {{identity}}
    ORDER BY v.valid_from DESC NULLS LAST, v.key DESC
    LIMIT 1
)"""


def article_end_sql(alias: str) -> str:
    """SQL: the ``valid_until`` of the newest version of the article *alias* (null while it
    holds, and for an article without versions), its versions found as
    ``db.queries.articles`` finds them: by ``(bwb_id, stam_id)``, else by ``(bwb_id,
    article_number)``, each from its index."""
    by_stam = _NEWEST_VERSION.format(
        alias=alias, identity=f"v.stam_id = {alias}.stam_id"
    )
    by_number = _NEWEST_VERSION.format(
        alias=alias, identity=f"v.article_number = {alias}.article_number"
    )
    return (
        f"(CASE WHEN {alias}.bwb_id IS NULL THEN NULL"
        f" WHEN {alias}.stam_id IS NOT NULL THEN {by_stam} ELSE {by_number} END)"
    )


def article_end(store: GraphStore, article_id: str) -> str | None:
    """The ``valid_until`` of the newest version of the article *article_id*."""
    ended = next(
        store.query(
            f"SELECT {article_end_sql('r')} FROM {COLLECTION_ARTICLES} r"
            " WHERE r.id = %(id)s",
            {"id": article_id},
        ),
        None,
    )
    return str(ended) if ended else None


# The laws the articles of a law pass to (``TRANSPOSED_TO``: to an article of the new law, by
# its ``PART_OF``, or to the new law itself), each with the number of its articles that do,
# the most first. Its articles are read from its ``PART_OF`` edges, their edges from the index
# on ``from_id``.
_SUCCESSOR_LAWS = f"""
SELECT i.id, i.key, i.type, i.labels,
       json_build_object(
           'bwb_id', i.props -> 'bwb_id', 'celex', i.props -> 'celex',
           'official_id', i.props -> 'official_id', 'title', i.props -> 'title',
           'citation_title', i.props -> 'citation_title'
       ) AS props,
       count(DISTINCT e.from_id) AS articles
FROM edges a
JOIN edges e ON e.from_id = a.from_id AND e.relation = '{RELATION_TRANSPOSED_TO}'
LEFT JOIN LATERAL (
    SELECT p.to_id FROM edges p
    WHERE p.from_id = e.to_id AND p.relation = '{RELATION_PART_OF}'
      AND p.to_collection = '{COLLECTION_INSTRUMENTS}'
    ORDER BY p.to_id LIMIT 1
) part ON e.to_collection = '{COLLECTION_ARTICLES}'
JOIN {COLLECTION_INSTRUMENTS} i ON i.id = coalesce(part.to_id, e.to_id)
WHERE a.to_id = %(law)s AND a.relation = '{RELATION_PART_OF}'
  AND a.from_collection = '{COLLECTION_ARTICLES}'
  AND i.id <> %(law)s
GROUP BY i.id
ORDER BY articles DESC NULLS LAST, i.key
"""


def successor_laws(store: GraphStore, law_id: str) -> list[dict[str, Any]]:
    """The laws that take the place of the law *law_id*: ``{id, key, type, labels, props,
    articles}``, the one most of its articles pass to first."""
    return list(store.query(_SUCCESSOR_LAWS, {"law": law_id}))


def source_as_of(store: GraphStore, source: str | None) -> str | None:
    """The Dutch day the data of *source* stands on: when its retrieves last all ended well
    (``completeness.source.as_of`` of ``/api/stats``); None for a source without one."""
    if not source:
        return None
    found = cached_data_as_of(store).get(source) or {}
    moment = ((found.get("completeness") or {}).get("source") or {}).get("as_of")
    if not moment:
        return None
    return dutch_day(moment)
