"""Semantic relationship queries.

Back the /api/relationships endpoints and the article relationships view. The semantic
layer of an article-to-article REFERS_TO edge lives on the edge document: ``semantic_type``
and ``explanation``, written by ``semantic bwb-relation-types``.
"""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ANNEXES,
    COLLECTION_ARTICLES,
    COLLECTION_EDGES,
    RELATION_PART_OF,
    RELATION_REFERS_TO,
    RELATION_SCOPED_BY,
)
from lawgraph.db import ArangoStore
from lawgraph.db.queries.instrument_scope import scope_of

# Relations that participate in the semantic relationship layer between articles.
ARTICLE_RELATIONS: tuple[str, ...] = (RELATION_REFERS_TO,)

# Sub-query fragment: parent instrument of an article (edges go article → instrument).
_INSTRUMENT_FOR = f"""
    FIRST(
        FOR pe IN {COLLECTION_EDGES}
            FILTER pe._from == {{target}} AND pe.relation == '{RELATION_PART_OF}'
            LET inst = DOCUMENT(pe._to)
            FILTER inst != null
            LIMIT 1
            RETURN inst
    )
"""


def get_article_relationship_data(
    store: ArangoStore,
    article_id: str,
) -> dict[str, list[dict[str, Any]]]:
    """Return upstream/downstream article relationships plus annex scope links.

    * upstream — outgoing article references (this article depends on the target)
    * downstream — incoming article references (other articles rely on this one)
    * scope — outgoing SCOPED_BY edges to annex nodes

    REFERS_TO also carries references from judgments and documents, so both
    directions are restricted to article endpoints.
    """
    instrument_for_target = _INSTRUMENT_FOR.format(target="edge._to")
    instrument_for_source = _INSTRUMENT_FOR.format(target="edge._from")

    aql = f"""
    LET upstream = (
        FOR edge IN {COLLECTION_EDGES}
            FILTER edge._from == @article_id
            FILTER edge.relation IN @relations
            FILTER STARTS_WITH(edge._to, '{COLLECTION_ARTICLES}/')
            LET target = DOCUMENT(edge._to)
            FILTER target != null
            RETURN {{ edge: edge, target: target, instrument: {instrument_for_target} }}
    )
    LET downstream = (
        FOR edge IN {COLLECTION_EDGES}
            FILTER edge._to == @article_id
            FILTER edge.relation IN @relations
            FILTER STARTS_WITH(edge._from, '{COLLECTION_ARTICLES}/')
            LET target = DOCUMENT(edge._from)
            FILTER target != null
            RETURN {{ edge: edge, target: target, instrument: {instrument_for_source} }}
    )
    LET scope = (
        FOR edge IN {COLLECTION_EDGES}
            FILTER edge._from == @article_id
            FILTER edge.relation == '{RELATION_SCOPED_BY}'
            FILTER STARTS_WITH(edge._to, '{COLLECTION_ANNEXES}/')
            LET annex = DOCUMENT(edge._to)
            FILTER annex != null
            RETURN {{ edge: edge, annex: annex }}
    )
    RETURN {{ upstream: upstream, downstream: downstream, scope: scope }}
    """
    rows = list(
        store.query(
            aql,
            {"article_id": article_id, "relations": list(ARTICLE_RELATIONS)},
        )
    )
    if rows:
        return rows[0]
    return {"upstream": [], "downstream": [], "scope": []}


def search_relationships(
    store: ArangoStore,
    *,
    semantic_type: str | None = None,
    bwb_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Return classified edges filtered by semantic_type and/or source-article law.

    Returns (rows, total). Each row: {edge, source_article, target}.
    """
    filters = ["edge.semantic_type != null"]
    bind: dict[str, Any] = {"limit": limit, "offset": offset}
    if semantic_type:
        filters.append("edge.semantic_type == @semantic_type")
        bind["semantic_type"] = semantic_type

    if bwb_id:
        # Drive from the article index, not a full edge scan.
        bind["bwb_id"] = bwb_id
        aql = f"""
        // The matches are kept as ids: every classified edge of a law with its article
        // (text included) is hundreds of MB to count them and show fifty.
        LET matches = (
            FOR art IN {COLLECTION_ARTICLES}
                FILTER art.props.bwb_id == @bwb_id
                FOR edge IN {COLLECTION_EDGES}
                    FILTER edge._from == art._id
                    FILTER {" AND ".join(filters)}
                    RETURN edge._id
        )
        LET total = LENGTH(matches)
        LET page = (
            FOR edge_id IN matches
                LIMIT @offset, @limit
                LET edge = DOCUMENT(edge_id)
                LET source_article = DOCUMENT(edge._from)
                LET target = DOCUMENT(edge._to)
                FILTER source_article != null AND target != null
                RETURN {{ edge: edge, source_article: source_article, target: target }}
        )
        RETURN {{ rows: page, total: total }}
        """
    else:
        aql = f"""
        LET matches = (
            FOR edge IN {COLLECTION_EDGES}
                FILTER {" AND ".join(filters)}
                RETURN edge._id
        )
        LET total = LENGTH(matches)
        LET page = (
            FOR edge_id IN matches
                LIMIT @offset, @limit
                LET edge = DOCUMENT(edge_id)
                LET source_article = DOCUMENT(edge._from)
                LET target = DOCUMENT(edge._to)
                FILTER source_article != null AND target != null
                RETURN {{ edge: edge, source_article: source_article, target: target }}
        )
        RETURN {{ rows: page, total: total }}
        """
    result = list(store.query(aql, bind))
    if result:
        return list(result[0].get("rows") or []), int(result[0].get("total") or 0)
    return [], 0


def get_cross_law_dependencies(
    store: ArangoStore,
    identifier: str,
    *,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Return article references from a BWB id or CELEX number into articles of other laws.

    Each row: {edge, source_article, target}. Driven by the
    (props.bwb_id, props.article_number) or (props.celex, props.article_number) index on
    ``articles``. The other law of a BWB regulation is a BWB regulation; the other law of
    an EU act is a BWB regulation or another EU act.
    """
    scope = scope_of(identifier)
    other_law = (
        "target.props.bwb_id != null AND target.props.bwb_id != @bwb_id"
        if scope.prop == "bwb_id"
        else (
            "(target.props.bwb_id != null OR target.props.celex != null)"
            " AND target.props.celex != @bwb_id"
        )
    )
    aql = f"""
    FOR art IN {COLLECTION_ARTICLES}
        FILTER art.props.{scope.prop} == @bwb_id
        FOR edge IN {COLLECTION_EDGES}
            FILTER edge._from == art._id
            FILTER edge.relation IN @relations
            FILTER STARTS_WITH(edge._to, '{COLLECTION_ARTICLES}/')
            LET target = DOCUMENT(edge._to)
            FILTER target != null
            FILTER {other_law}
            LIMIT @limit
            RETURN {{ edge: edge, source_article: art, target: target }}
    """
    return list(
        store.query(
            aql,
            {
                "bwb_id": scope.value,
                "relations": list(ARTICLE_RELATIONS),
                "limit": limit,
            },
        )
    )
