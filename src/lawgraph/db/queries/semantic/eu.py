"""The reads of the semantic phase for EUR-Lex: the EU articles and the national measures
that implement a directive.

A read whose order ArangoDB left open comes in the order of the keys."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import (
    RAW_KIND_EU_NIM,
    SOURCE_BWB,
    SOURCE_EURLEX,
)
from lawgraph.db.counting import Store
from lawgraph.db.queries.semantic import nonempty_sql, slim_sql


def _or_empty_list(value: str) -> str:
    """SQL for ``value || []`` of the json *value*: the value when it is truthy (an array
    or object, even an empty one; a non-empty string; a number other than 0; ``true``),
    else ``[]``."""
    return f"""coalesce(CASE json_typeof({value})
        WHEN 'array' THEN {value}
        WHEN 'object' THEN {value}
        WHEN 'string' THEN CASE WHEN {value} #>> '{{}}' <> '' THEN {value} END
        WHEN 'number' THEN CASE WHEN ({value} #>> '{{}}')::numeric <> 0 THEN {value} END
        WHEN 'boolean' THEN CASE WHEN {value} #>> '{{}}' = 'true' THEN {value} END
    END, '[]'::json)"""


_EU_REFERENCES_SQL = f"""
SELECT props -> 'bwb_id' AS bwb_id,
       {_or_empty_list("props -> 'celex_refs'")} AS named,
       {_or_empty_list("props -> 'implements_celex'")} AS implements
FROM instruments
WHERE lg_str(props -> 'source') = %(source)s
  AND ({nonempty_sql("props -> 'celex_refs'")}
       OR {nonempty_sql("props -> 'implements_celex'")})
ORDER BY key
"""


def eu_references(store: Store) -> Iterator[dict[str, Any]]:
    """``{bwb_id, named, implements}`` of the BWB regulations that name an EU act or whose
    considerans says they implement one (CELEX numbers)."""
    return store.query(_EU_REFERENCES_SQL, {"source": SOURCE_BWB})


def national_measures(store: Store) -> Iterator[Any]:
    """The national implementing measures of EUR-Lex as retrieved (``payload_json``), in
    the order of their records."""
    return store.query(
        """
        SELECT doc -> 'payload_json' FROM raw_sources
        WHERE source = %(source)s AND kind = %(kind)s
          AND json_typeof(doc -> 'payload_json') <> 'null'
        ORDER BY source, kind, key
        """,
        {"source": SOURCE_EURLEX, "kind": RAW_KIND_EU_NIM},
    )


# UNION_DISTINCT of the two: every pair once, where it first occurs (the regulations by key,
# then the versions' pairs in the order COLLECT gave them: sorted, null first).
_REGULATIONS_OF_PUBLICATIONS_SQL = """
WITH pairs AS (
    SELECT lg_str(r.props -> 'enacted_publication') AS publication, r.bwb_id,
           1 AS part, row_number() OVER (ORDER BY r.key) AS n
    FROM instruments r
    WHERE lg_str(r.props -> 'source') = %(source)s
      AND lg_str(r.props -> 'enacted_publication') = ANY(%(publications)s)
    UNION ALL
    SELECT publication, bwb_id, 2 AS part,
           row_number() OVER (ORDER BY publication NULLS FIRST, bwb_id NULLS FIRST) AS n
    FROM (
        SELECT DISTINCT lg_str(v.props -> 'origin_publication' -> 'id') AS publication,
               v.bwb_id
        FROM article_versions v
        WHERE lg_str(v.props -> 'origin_publication' -> 'id') = ANY(%(publications)s)
    ) collected
),
first_pairs AS (
    SELECT DISTINCT ON (publication, bwb_id) publication, bwb_id, part, n
    FROM pairs
    ORDER BY publication, bwb_id, part, n
)
SELECT json_build_array(publication, bwb_id) FROM first_pairs ORDER BY part, n
"""


def regulations_of_publications(
    store: Store, publications: list[str]
) -> Iterator[list[str]]:
    """``[publication id, bwb_id]`` for every regulation one of *publications* enacted
    (``props.enacted_publication``) or made a version of an article of (its origin)."""
    return store.query(
        _REGULATIONS_OF_PUBLICATIONS_SQL,
        {"source": SOURCE_BWB, "publications": publications},
    )


_EU_ARTICLES_OF_SQL = f"""
SELECT {slim_sql("a", "celex", "article_number", "text", "display_name")}
FROM articles a
WHERE a.celex = ANY(%(celex_list)s)
ORDER BY a.key
"""

_EU_ARTICLES_SQL = f"""
SELECT {slim_sql("a", "celex", "article_number", "text", "display_name")}
FROM articles a
WHERE a.celex IS NOT NULL
ORDER BY a.key
"""


def eu_articles_of(store: Store, celex_list: list[str]) -> Iterator[dict[str, Any]]:
    """The articles of the EU acts in *celex_list*, with their text."""
    return store.query(_EU_ARTICLES_OF_SQL, {"celex_list": celex_list})


def eu_articles(store: Store) -> Iterator[dict[str, Any]]:
    """The articles of every EU act, with their text."""
    return store.query(_EU_ARTICLES_SQL)
