"""Annex query helpers — detail, referenced-by, and cross-law views."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ANNEXES,
    COLLECTION_ARTICLES,
    COLLECTION_EDGES,
    RELATION_SCOPED_BY,
)
from lawgraph.db import ArangoStore


def get_annex(store: ArangoStore, key: str) -> dict[str, Any] | None:
    """Return an annex document by key, or None when unknown."""
    doc = store.collection(COLLECTION_ANNEXES).get(key)
    return doc if isinstance(doc, dict) else None


def get_annex_referenced_by(
    store: ArangoStore,
    key: str,
) -> list[dict[str, Any]]:
    """Return articles (across all laws) linked to this annex via SCOPED_BY.

    Each row: {edge, article}.
    """
    annex_id = f"{COLLECTION_ANNEXES}/{key}"
    aql = f"""
    FOR edge IN {COLLECTION_EDGES}
        FILTER edge._to == @annex_id
        FILTER edge.relation == '{RELATION_SCOPED_BY}'
        LET article = DOCUMENT(edge._from)
        FILTER article != null
        RETURN {{ edge: edge, article: article }}
    """
    return list(store.query(aql, {"annex_id": annex_id}))


def list_annexes(
    store: ArangoStore,
    *,
    bwb_id: str | None = None,
    shared_across_laws: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Return annexes, optionally filtered to one law or to cross-law shared ones.

    Each row: {annex, referencing_laws: [bwb_id, ...]}. ``shared_across_laws``
    keeps only annexes referenced by articles of at least two distinct laws
    (including the owning law itself).

    Returns (rows, total).
    """
    filters = []
    bind: dict[str, Any] = {"limit": limit, "offset": offset}
    if bwb_id:
        filters.append("b.props.bwb_id == @bwb_id")
        bind["bwb_id"] = bwb_id
    filter_clause = f"FILTER {' AND '.join(filters)}" if filters else ""
    shared_clause = (
        "FILTER LENGTH(row.referencing_laws) >= 2" if shared_across_laws else ""
    )

    aql = f"""
    LET matches = (
        FOR b IN {COLLECTION_ANNEXES}
            {filter_clause}
            LET referencing_laws = UNIQUE(
                FOR edge IN {COLLECTION_EDGES}
                    FILTER edge._to == b._id
                    FILTER edge.relation == '{RELATION_SCOPED_BY}'
                    LET article = DOCUMENT(edge._from)
                    FILTER article != null AND article.props.bwb_id != null
                    RETURN article.props.bwb_id
            )
            LET row = {{ annex: b, referencing_laws: referencing_laws }}
            {shared_clause}
            RETURN row
    )
    LET total = LENGTH(matches)
    LET page = (FOR m IN matches SORT m.annex._key LIMIT @offset, @limit RETURN m)
    RETURN {{ rows: page, total: total }}
    """
    result = list(store.query(aql, bind))
    if result:
        return list(result[0].get("rows") or []), int(result[0].get("total") or 0)
    return [], 0


def get_shared_annexes_for_law(
    store: ArangoStore,
    bwb_id: str,
) -> list[dict[str, Any]]:
    """Return annexes connecting *bwb_id* to other laws.

    Covers both directions: annexes owned by this law that other laws'
    articles reference, and annexes of other laws referenced by this
    law's articles. Each row: {annex, referencing_laws}.
    """
    aql = f"""
    LET own = (
        FOR b IN {COLLECTION_ANNEXES}
            FILTER b.props.bwb_id == @bwb_id
            RETURN b
    )
    LET foreign = UNIQUE(
        FOR art IN {COLLECTION_ARTICLES}
            FILTER art.props.bwb_id == @bwb_id
            FOR edge IN {COLLECTION_EDGES}
                FILTER edge._from == art._id
                FILTER edge.relation == '{RELATION_SCOPED_BY}'
                LET b = DOCUMENT(edge._to)
                FILTER b != null AND b.props.bwb_id != @bwb_id
                RETURN b
    )
    FOR b IN APPEND(own, foreign)
        LET referencing_laws = UNIQUE(
            FOR edge IN {COLLECTION_EDGES}
                FILTER edge._to == b._id
                FILTER edge.relation == '{RELATION_SCOPED_BY}'
                LET article = DOCUMENT(edge._from)
                FILTER article != null AND article.props.bwb_id != null
                RETURN article.props.bwb_id
        )
        FILTER LENGTH(
            FOR law IN referencing_laws FILTER law != b.props.bwb_id RETURN 1
        ) > 0 OR b.props.bwb_id != @bwb_id
        RETURN {{ annex: b, referencing_laws: referencing_laws }}
    """
    return list(store.query(aql, {"bwb_id": bwb_id}))
