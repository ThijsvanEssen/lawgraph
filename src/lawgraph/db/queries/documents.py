"""Queries behind the document endpoints."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLE_VERSIONS,
    COLLECTION_ARTICLES,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_EDGES,
    COLLECTION_INSTRUMENTS,
    RELATION_EXPLAINS,
    RELATION_PART_OF,
    RELATION_VERSION_OF,
)
from lawgraph.core.models import make_node_key
from lawgraph.db import ArangoStore


def get_document(store: ArangoStore, key: str) -> dict[str, Any] | None:
    """One document by key (keys are lowercased at ingest)."""
    doc = store.collection(COLLECTION_DOCUMENTS).get(key.lower())
    return doc if isinstance(doc, dict) else None


def get_document_links(store: ArangoStore, document_id: str) -> dict[str, Any]:
    """The dossiers a document is PART_OF and the articles or laws it EXPLAINS.

    ``dossier_numbers`` come from the PART_OF edges to dossier nodes, which both
    chambers write (an Eerste Kamer paper names its dossier in ``dossier_number``, a
    Tweede Kamer one in ``dossier_numbers``), so it is the number the ``dossier``
    filters use, with its suffix for a chapter (``37020-XV``). ``explains`` resolves
    each EXPLAINS target to what a reader cites: an article version to its article
    (through VERSION_OF; a version without an article is left out), an article as it
    is, an instrument as ``instruments``.
    """
    aql = f"""
    LET dossier_numbers = SORTED_UNIQUE((
        FOR e IN {COLLECTION_EDGES}
            FILTER e._from == @document_id AND e.relation == @part_of
            FILTER STARTS_WITH(e._to, '{COLLECTION_DOSSIERS}/')
            LET dossier = DOCUMENT(e._to)
            FILTER dossier != null AND dossier.props.label != null
            RETURN dossier.props.label
    ))
    LET targets = (
        FOR e IN {COLLECTION_EDGES}
            FILTER e._from == @document_id AND e.relation == @explains
            LET target = STARTS_WITH(e._to, '{COLLECTION_ARTICLE_VERSIONS}/') ? FIRST(
                FOR v IN {COLLECTION_EDGES}
                    FILTER v._from == e._to AND v.relation == @version_of
                    FILTER STARTS_WITH(v._to, '{COLLECTION_ARTICLES}/')
                    LIMIT 1
                    RETURN DOCUMENT(v._to)
            ) : DOCUMENT(e._to)
            FILTER target != null
            LET collection = PARSE_IDENTIFIER(target._id).collection
            FILTER collection IN ['{COLLECTION_ARTICLES}', '{COLLECTION_INSTRUMENTS}']
            RETURN {{
                id: target._id,
                key: target._key,
                collection: collection,
                bwb_id: target.props.bwb_id,
                article_number: collection == '{COLLECTION_ARTICLES}'
                    ? target.props.article_number : null
            }}
    )
    RETURN {{
        dossier_numbers: dossier_numbers,
        explains: (FOR target IN UNIQUE(targets) SORT target.id RETURN target)
    }}
    """
    bind = {
        "document_id": document_id,
        "part_of": RELATION_PART_OF,
        "explains": RELATION_EXPLAINS,
        "version_of": RELATION_VERSION_OF,
    }
    rows = list(store.query(aql, bind))
    return rows[0] if rows else {"dossier_numbers": [], "explains": []}


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
