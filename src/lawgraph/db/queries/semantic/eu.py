"""The reads of the semantic phase for EUR-Lex: the EU articles and the national measures
that implement a directive."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLE_VERSIONS,
    COLLECTION_ARTICLES,
    COLLECTION_INSTRUMENTS,
    COLLECTION_RAW_SOURCES,
    RAW_KIND_EU_NIM,
    SOURCE_BWB,
    SOURCE_EURLEX,
)
from lawgraph.db.counting import Store
from lawgraph.db.queries.semantic import slim


def eu_references(store: Store) -> Iterator[dict[str, Any]]:
    """``{bwb_id, named, implements}`` of the BWB regulations that name an EU act or whose
    considerans says they implement one (CELEX numbers)."""
    aql = f"""
        FOR regulation IN {COLLECTION_INSTRUMENTS}
            FILTER regulation.props.source == @source
            FILTER LENGTH(regulation.props.celex_refs) > 0
                OR LENGTH(regulation.props.implements_celex) > 0
            RETURN {{
                bwb_id: regulation.props.bwb_id,
                named: regulation.props.celex_refs || [],
                implements: regulation.props.implements_celex || []
            }}
        """
    return store.query(aql, {"source": SOURCE_BWB})


def national_measures(store: Store) -> Iterator[Any]:
    """The national implementing measures of EUR-Lex as retrieved (``payload_json``)."""
    aql = f"""
        FOR r IN {COLLECTION_RAW_SOURCES}
            FILTER r.source == @source AND r.kind == @kind AND r.payload_json != null
            RETURN r.payload_json
        """
    return store.query(aql, {"source": SOURCE_EURLEX, "kind": RAW_KIND_EU_NIM})


def regulations_of_publications(
    store: Store, publications: list[str]
) -> Iterator[list[str]]:
    """``[publication id, bwb_id]`` for every regulation one of *publications* enacted
    (``props.enacted_publication``) or made a version of an article of (its origin)."""
    aql = f"""
        FOR pair IN UNION_DISTINCT(
            (
                FOR regulation IN {COLLECTION_INSTRUMENTS}
                    FILTER regulation.props.source == @source
                    FILTER regulation.props.enacted_publication IN @publications
                    RETURN [regulation.props.enacted_publication, regulation.props.bwb_id]
            ),
            (
                FOR v IN {COLLECTION_ARTICLE_VERSIONS}
                    FILTER v.props.origin_publication.id IN @publications
                    COLLECT publication = v.props.origin_publication.id,
                        bwb_id = v.props.bwb_id
                    RETURN [publication, bwb_id]
            )
        )
            RETURN pair
        """
    return store.query(aql, {"source": SOURCE_BWB, "publications": publications})


def eu_articles_of(store: Store, celex_list: list[str]) -> Iterator[dict[str, Any]]:
    """The articles of the EU acts in *celex_list*, with their text."""
    aql = f"""
            FOR doc IN {COLLECTION_ARTICLES}
                FILTER doc.props.celex IN @celex_list
                RETURN {slim("doc", "celex", "article_number", "text", "display_name")}
            """
    return store.query(aql, bind_vars={"celex_list": celex_list})


def eu_articles(store: Store) -> Iterator[dict[str, Any]]:
    """The articles of every EU act, with their text."""
    aql = f"""
            FOR doc IN {COLLECTION_ARTICLES}
                FILTER doc.props.celex != null
                RETURN {slim("doc", "celex", "article_number", "text", "display_name")}
            """
    return store.query(aql)
