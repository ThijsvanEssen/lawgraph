"""Semantic relationship query helpers.

Backs the /api/relationships endpoints and the article relationships view.
Semantic metadata lives on edge documents as top-level fields:
``semantic_type``, ``semantic_source``, ``expert_badge``, ``explanation``,
``community_upvotes``, ``community_downvotes``, ``created_by``.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ANNEXES,
    COLLECTION_ARTICLES,
    COLLECTION_EDGES,
    EDGE_STATUS_CANONIEK,
    RELATION_PART_OF,
    RELATION_REFERS_TO,
    RELATION_SCOPED_BY,
    SEMANTIC_RELATIONSHIP_TYPES,
    SEMANTIC_SOURCES,
)
from lawgraph.core.models import make_node_key
from lawgraph.core.time import iso_timestamp
from lawgraph.db import ArangoStore
from lawgraph.db import edge_key as _sha1_edge_key
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


def _parse_article_ref(ref: str) -> tuple[str, str]:
    """Parse a 'BWBR0001854/287' style article reference into (bwb_id, article_number)."""
    parts = ref.strip().split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(
            f"Article reference must look like 'BWBR0001854/287'; got {ref!r}"
        )
    return parts[0], parts[1]


def resolve_article_id(store: ArangoStore, ref: str) -> str:
    """Resolve a 'bwb_id/article_number' reference to an existing article _id.

    Raises ValueError if the reference is malformed or the article is unknown.
    """
    bwb_id, article_number = _parse_article_ref(ref)
    key = make_node_key(bwb_id, article_number)
    doc = store.articles.get(key)
    if doc is None:
        raise ValueError(f"Article {bwb_id} {article_number} not found")
    return f"{COLLECTION_ARTICLES}/{key}"


def tag_relationship(
    store: ArangoStore,
    *,
    source_article_id: str,
    target_article_id: str,
    semantic_type: str,
    explanation: str | None,
    semantic_source: str,
    expert_badge: bool = False,
    created_by: str | None = None,
) -> dict[str, Any]:
    """Create or update a REFERS_TO edge with curated semantic metadata.

    Raises ValueError on invalid semantic_type/semantic_source.
    """
    if semantic_type not in SEMANTIC_RELATIONSHIP_TYPES:
        raise ValueError(f"Unknown semantic_type {semantic_type!r}")
    if semantic_source not in SEMANTIC_SOURCES:
        raise ValueError(f"Unknown semantic_source {semantic_source!r}")

    now = iso_timestamp(dt.datetime.now(dt.timezone.utc).replace(microsecond=0))
    e_key = _sha1_edge_key(source_article_id, RELATION_REFERS_TO, target_article_id)
    insert_doc: dict[str, Any] = {
        "_key": e_key,
        "_from": source_article_id,
        "_to": target_article_id,
        "relation": RELATION_REFERS_TO,
        "source": "curation-api",
        "status": EDGE_STATUS_CANONIEK,
        "confidence": 1.0,
        "meta": {},
        "semantic_type": semantic_type,
        "semantic_source": semantic_source,
        "expert_badge": expert_badge,
        "explanation": explanation,
        "community_upvotes": 0,
        "community_downvotes": 0,
        "created_by": created_by,
        "created_at": now,
        "updated_at": now,
    }
    aql = f"""
    UPSERT {{ _key: @key }}
    INSERT @insert_doc
    UPDATE {{
        semantic_type: @semantic_type,
        semantic_source: @semantic_source,
        expert_badge: @expert_badge,
        explanation: @explanation,
        created_by: @created_by,
        updated_at: @now
    }}
    IN {COLLECTION_EDGES}
    RETURN NEW
    """
    rows = list(
        store.query(
            aql,
            {
                "key": e_key,
                "insert_doc": insert_doc,
                "semantic_type": semantic_type,
                "semantic_source": semantic_source,
                "expert_badge": expert_badge,
                "explanation": explanation,
                "created_by": created_by,
                "now": now,
            },
        )
    )
    return rows[0] if rows else insert_doc


def vote_relationship(
    store: ArangoStore,
    edge_key: str,
    vote: str,
) -> dict[str, Any] | None:
    """Atomically increment a community vote counter on an edge.

    ``vote`` must be 'upvote' or 'downvote'. Returns the updated edge,
    or None when the edge does not exist.
    """
    if vote not in ("upvote", "downvote"):
        raise ValueError(f"vote must be 'upvote' or 'downvote'; got {vote!r}")
    field = "community_upvotes" if vote == "upvote" else "community_downvotes"
    aql = f"""
    FOR edge IN {COLLECTION_EDGES}
        FILTER edge._key == @key
        UPDATE edge WITH {{ {field}: (edge.{field} || 0) + 1 }} IN {COLLECTION_EDGES}
        RETURN NEW
    """
    rows = list(store.query(aql, {"key": edge_key}))
    return rows[0] if rows else None


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
