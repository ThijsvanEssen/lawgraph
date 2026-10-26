"""The reads of the semantic phase for EUR-Lex: the EU articles and the national measures
that implement a directive.

Rows come in the order of the keys, so a run reads them in the same order every time."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import (
    RAW_KIND_EURLEX_NIM,
    SOURCE_BWB,
    SOURCE_EURLEX,
)
from lawgraph.db.counting import Store
from lawgraph.db.queries._json_sql import EMPTY_ARRAY, has_length, is_present, truthy_or
from lawgraph.db.queries.semantic import slim_sql

_EU_REFERENCES_SQL = f"""
SELECT props -> 'bwb_id' AS bwb_id,
       {truthy_or("props -> 'celex_refs'", EMPTY_ARRAY)} AS named,
       {truthy_or("props -> 'implements_celex'", EMPTY_ARRAY)} AS implements
FROM instruments
WHERE lg_str(props -> 'source') = %(source)s
  AND ({has_length("props -> 'celex_refs'")}
       OR {has_length("props -> 'implements_celex'")})
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
        f"""
        SELECT doc -> 'payload_json' FROM raw_sources
        WHERE source = %(source)s AND kind = %(kind)s
          AND {is_present("doc -> 'payload_json'")}
        ORDER BY source, kind, key
        """,
        {"source": SOURCE_EURLEX, "kind": RAW_KIND_EURLEX_NIM},
    )


# The regulations each publication enacted, every pair once, by key. A regulation a
# publication merely changed is not one: an amending act names no regulation that implements.
_REGULATIONS_OF_PUBLICATIONS_SQL = """
SELECT json_build_array(publication, bwb_id)
FROM (
    SELECT DISTINCT ON (publication, bwb_id) publication, bwb_id, key
    FROM (
        SELECT lg_str(r.props -> 'enacted_publication') AS publication, r.bwb_id, r.key
        FROM instruments r
        WHERE lg_str(r.props -> 'source') = %(source)s
          AND lg_str(r.props -> 'enacted_publication') = ANY(%(publications)s)
    ) enacted
    ORDER BY publication, bwb_id, key
) pairs
ORDER BY key
"""


def regulations_of_publications(
    store: Store, publications: list[str]
) -> Iterator[list[str]]:
    """``[publication id, bwb_id]`` for every regulation one of *publications* enacted
    (``props.enacted_publication``)."""
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
