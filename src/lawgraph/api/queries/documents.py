"""Queries behind the document endpoints."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLE_VERSIONS,
    COLLECTION_ARTICLES,
    COLLECTION_DOCUMENTS,
    COLLECTION_EDGES,
    RELATION_EXPLAINS,
    RELATION_REFERS_TO,
)
from lawgraph.core.models import make_node_key
from lawgraph.db import ArangoStore


def get_document(store: ArangoStore, key: str) -> dict[str, Any] | None:
    """One document by key (keys are lowercased at ingest)."""
    doc = store.collection(COLLECTION_DOCUMENTS).get(key.lower())
    return doc if isinstance(doc, dict) else None


def list_documents(
    store: ArangoStore,
    *,
    q: str | None,
    kind: str | None,
    chamber: str | None,
    source: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Document rows with the number of articles each one links to.

    The count is computed for the limited page only, so the whole list is one
    round trip.
    """
    filters: list[str] = []
    bind: dict[str, Any] = {
        "limit": limit,
        "linking": [RELATION_REFERS_TO, RELATION_EXPLAINS],
    }

    if chamber:
        filters.append("FILTER @chamber IN document.labels")
        bind["chamber"] = chamber.upper()
    if source:
        filters.append("FILTER document.props.source == @source")
        bind["source"] = source
    if kind:
        filters.append("FILTER document.props.kind == @kind")
        bind["kind"] = kind
    if q:
        filters.append(
            "FILTER CONTAINS(LOWER(document.props.title), LOWER(@q))"
            " OR CONTAINS(LOWER(document.props.kind), LOWER(@q))"
        )
        bind["q"] = q

    aql = f"""
FOR document IN {COLLECTION_DOCUMENTS}
    {chr(10).join(f"    {f}" for f in filters)}
    SORT document.props.date DESC, document.props.title ASC
    LIMIT @limit
    LET linked = LENGTH(
        FOR e IN {COLLECTION_EDGES}
            FILTER e._from == document._id
            FILTER e.relation IN @linking
            RETURN 1
    )
    RETURN {{
        key: document._key,
        title: document.props.title,
        kind: document.props.kind,
        date: document.props.date,
        external_id: document.props.external_id,
        source: document.props.source,
        has_text: document.props.text != null,
        linked_articles: linked
    }}
"""
    return list(store.query(aql, bind_vars=bind))


def get_document_passages(
    store: ArangoStore, document_id: str, bwb_id: str, article_number: str
) -> list[dict[str, Any]]:
    """The sections of a document that explain an article, one row per section.

    The edges are ``EXPLAINS`` from the document to the article or to one of its versions
    (the same ``bwb_id`` and ``stam_id``), each with the sections in ``meta.sections``. A
    section that several of those edges name is one row, with the highest confidence.
    Unsorted; an unknown article has none.
    """
    article = store.collection(COLLECTION_ARTICLES).get(
        make_node_key(bwb_id, article_number)
    )
    if not isinstance(article, dict):
        return []
    props = article.get("props") or {}
    targets = [article["_id"]]
    if props.get("stam_id"):
        targets += store.query(
            f"""
            FOR v IN {COLLECTION_ARTICLE_VERSIONS}
                FILTER v.props.bwb_id == @bwb_id AND v.props.stam_id == @stam_id
                RETURN v._id
            """,
            bind_vars={"bwb_id": props.get("bwb_id"), "stam_id": props["stam_id"]},
        )
    edges = store.query(
        f"""
        FOR e IN {COLLECTION_EDGES}
            FILTER e._from == @document_id AND e.relation == @explains
            FILTER e._to IN @targets
            FILTER IS_ARRAY(e.meta.sections)
            RETURN e.meta.sections
        """,
        bind_vars={
            "document_id": document_id,
            "explains": RELATION_EXPLAINS,
            "targets": targets,
        },
    )
    best: dict[str, dict[str, Any]] = {}
    for sections in edges:
        for section in sections:
            known = best.get(section["section_anchor"])
            if known is None or section["confidence"] > known["confidence"]:
                best[section["section_anchor"]] = section
    return list(best.values())
