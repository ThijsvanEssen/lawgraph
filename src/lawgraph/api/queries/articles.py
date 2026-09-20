"""Article query helpers."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from lawgraph.api.queries._helpers import (
    _coerce_float,
    _coerce_int,
    _coerce_text,
    _ensure_doc,
    _extract_confidence,
    _extract_span,
    _find_instrument_for_article,
    _find_judgments_for_article,
    _load_document_by_ref,
    _resolve_target_from_entry,
)
from lawgraph.api.queries.dossiers import collect_dossier_numbers, get_dossier_titles
from lawgraph.config.constants import (
    COLLECTION_ARTICLE_VERSIONS,
    COLLECTION_ARTICLES,
    COLLECTION_DOSSIERS,
    COLLECTION_EDGES,
    EDGE_STATUS_VOORGESTELD,
    RELATION_AMENDS,
    RELATION_EXPLAINS,
    RELATION_INTRODUCES,
    RELATION_PART_OF,
    RELATION_REFERS_TO,
    RELATION_REPEALS,
)
from lawgraph.core.models import make_node_key
from lawgraph.db import ArangoStore


@dataclass
class ArticleDetailData:
    article: dict[str, Any]
    instrument: dict[str, Any] | None
    judgments: list[dict[str, Any]]
    metadata: dict[str, Any]


@dataclass
class ArticleHistoryData:
    article: dict[str, Any]
    versions: list[dict[str, Any]]
    dossier_titles: dict[str, str | None]


@dataclass
class ArticleCitationEntry:
    target: dict[str, Any]
    start: int | None
    end: int | None
    text: str | None
    confidence: float | None


def _record_article_citation(
    citations: list[ArticleCitationEntry],
    seen: set[tuple[str, int | None, int | None, str | None]],
    target_doc: dict[str, Any],
    start: int | None,
    end: int | None,
    text: str | None,
    confidence: float | None,
) -> None:
    target_id = target_doc.get("_id")
    if not target_id:
        return
    key = (target_id, start, end, text)
    if key in seen:
        return
    seen.add(key)
    citations.append(
        ArticleCitationEntry(
            target=target_doc, start=start, end=end, text=text, confidence=confidence
        )
    )


def get_article_with_relations(
    store: ArangoStore,
    bwb_id: str,
    article_number: str,
) -> ArticleDetailData:
    """Fetch an article with its parent instrument and the judgments citing it."""
    article_key = make_node_key(bwb_id, article_number)
    article_doc = store.articles.get(article_key)
    article_doc = _ensure_doc(article_doc)
    if article_doc is None:
        raise ValueError("article not found")

    article_id = article_doc["_id"]
    instrument_doc = _find_instrument_for_article(store, article_id)
    judgments = _find_judgments_for_article(store, article_id)

    metadata = {"judgment_count": len(judgments)}
    return ArticleDetailData(
        article=article_doc,
        instrument=instrument_doc,
        judgments=judgments,
        metadata=metadata,
    )


def get_article_history(
    store: ArangoStore,
    bwb_id: str,
    article_number: str,
) -> ArticleHistoryData:
    """All versions of one article identity, oldest first, plus dossier titles.

    The current article is resolved by key (``ValueError`` when unknown). Its
    identity inside the regulation is ``(bwb_id, stam_id)``; an article without a
    ``stam_id`` is matched on ``(bwb_id, article_number)``. Query budget: one for
    the versions and, when the publications name dossiers, one for their titles —
    independent of the number of versions.
    """
    article_key = make_node_key(bwb_id, article_number)
    article = _ensure_doc(store.articles.get(article_key))
    if article is None:
        raise ValueError("article not found")

    props = article.get("props") or {}
    stam_id = props.get("stam_id")
    doc_bwb_id = props.get("bwb_id") or bwb_id.upper()
    if stam_id:
        identity_filter = "FILTER v.props.stam_id == @identity"
        identity = stam_id
    else:
        identity_filter = "FILTER v.props.article_number == @identity"
        identity = props.get("article_number") or article_number
    aql = f"""
    FOR v IN {COLLECTION_ARTICLE_VERSIONS}
        FILTER v.props.bwb_id == @bwb_id
        {identity_filter}
        SORT v.props.valid_from ASC, v._key ASC
        RETURN v
    """
    versions = list(store.query(aql, {"bwb_id": doc_bwb_id, "identity": identity}))

    publications = [
        (v.get("props") or {}).get(field)
        for v in versions
        for field in ("origin_publication", "commencement_publication")
    ]
    titles = get_dossier_titles(store, collect_dossier_numbers(publications))
    return ArticleHistoryData(article=article, versions=versions, dossier_titles=titles)


def get_article_citations(
    store: ArangoStore,
    article_doc: dict[str, Any],
) -> list[ArticleCitationEntry]:
    doc = _ensure_doc(article_doc)
    if not doc:
        return []
    article_id = doc.get("_id")
    if not article_id:
        return []

    citations: list[ArticleCitationEntry] = []
    seen: set[tuple[str, int | None, int | None, str | None]] = set()

    aql = f"""
    FOR edge IN {COLLECTION_EDGES}
        FILTER edge._from == @article_id
        FILTER edge.relation == @relation
        RETURN edge
    """
    for edge in store.query(
        aql, {"article_id": article_id, "relation": RELATION_REFERS_TO}
    ):
        target_doc = _load_document_by_ref(store, edge.get("_to"))
        if not target_doc:
            continue
        start, end, text = _extract_span(edge)
        confidence = _extract_confidence(edge)
        _record_article_citation(
            citations, seen, target_doc, start, end, text, confidence
        )

    props = doc.get("props") or {}
    raw_citations = props.get("citations")
    if isinstance(raw_citations, list):
        for entry in raw_citations:
            if not isinstance(entry, dict):
                continue
            target_doc = _resolve_target_from_entry(store, entry)
            if not target_doc:
                continue
            start = _coerce_int(entry.get("start"))
            end = _coerce_int(entry.get("end"))
            text = _coerce_text(entry.get("text"))
            confidence = _coerce_float(entry.get("confidence"))
            _record_article_citation(
                citations, seen, target_doc, start, end, text, confidence
            )

    return citations


def get_article_legislative_history(
    store: ArangoStore,
    bwb_id: str,
    article_number: str,
    article_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return dossiers/documents that introduced, amended, or propose to amend an article.

    Each entry: {dossier_id, dossier_number, dossier_title, date, kind, status,
    summary, document_id}.
    """
    if article_id is None:
        article_key = make_node_key(bwb_id, article_number)
        article_id = f"{COLLECTION_ARTICLES}/{article_key}"

    # Every edge pointing at this article that says something about its text.
    mutation_relations = [
        RELATION_AMENDS,
        RELATION_INTRODUCES,
        RELATION_REPEALS,
        RELATION_EXPLAINS,
        RELATION_REFERS_TO,
    ]
    aql = f"""
    FOR edge IN {COLLECTION_EDGES}
        FILTER edge._to == @article_id
        FILTER edge.relation IN @relations
        LET doc = DOCUMENT(edge._from)
        FILTER doc != null
        LET dossier = FIRST(
            FOR e2 IN {COLLECTION_EDGES}
                FILTER e2._from == edge._from AND e2.relation == '{RELATION_PART_OF}'
                FILTER STARTS_WITH(e2._to, '{COLLECTION_DOSSIERS}/')
                LET d = DOCUMENT(e2._to)
                FILTER d != null
                LIMIT 1 RETURN d
        )
        SORT edge.status == '{EDGE_STATUS_VOORGESTELD}' ? 0 : 1, doc.props.date DESC
        RETURN {{
            dossier_id: (dossier != null ? dossier._id : null),
            dossier_number: (dossier != null ? dossier.props.number : null),
            dossier_title: (dossier != null ? dossier.props.title : null),
            date: doc.props.date,
            kind: doc.props.kind,
            status: edge.status,
            summary: doc.props.display_name,
            document_id: doc._id
        }}
    """
    return list(
        store.query(
            aql,
            {
                "article_id": article_id,
                "relations": mutation_relations,
            },
        )
    )


def get_article_in_flux(
    store: ArangoStore, bwb_id: str, article_number: str, article_id: str | None = None
) -> dict[str, Any]:
    """In-flux status for an article: a flag plus the number of proposed edges."""
    if article_id is None:
        article_key = make_node_key(bwb_id, article_number)
        article_id = f"{COLLECTION_ARTICLES}/{article_key}"

    aql = f"""
    LET proposed = LENGTH(
        FOR edge IN {COLLECTION_EDGES}
            FILTER edge._to == @article_id
            FILTER edge.status == '{EDGE_STATUS_VOORGESTELD}'
            RETURN 1
    )
    RETURN {{ in_flux: proposed > 0, open_dossier_count: proposed }}
    """
    rows = list(store.query(aql, {"article_id": article_id}))
    if rows:
        return rows[0]
    return {"in_flux": False, "open_dossier_count": 0}


def get_articles_by_keys(
    store: ArangoStore, keys: Iterable[str]
) -> dict[str, dict[str, Any]]:
    """Fetch article documents for many keys in one query, keyed by ``_key``."""
    key_list = list(set(keys))
    if not key_list:
        return {}
    aql = f"""
    FOR doc IN {COLLECTION_ARTICLES}
        FILTER doc._key IN @keys
        RETURN doc
    """
    return {doc["_key"]: doc for doc in store.query(aql, {"keys": key_list})}
