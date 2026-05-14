"""Article query helpers."""

from __future__ import annotations

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
from lawgraph.config.settings import (
    COLLECTION_EDGES,
    EDGE_STATUS_VOORGESTELD,
    RELATION_REFERS_TO_ARTICLE,
)
from lawgraph.db import ArangoStore
from lawgraph.models import make_node_key


@dataclass
class ArticleDetailData:
    article: dict[str, Any]
    instrument: dict[str, Any] | None
    judgments: list[dict[str, Any]]
    metadata: dict[str, Any]


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
    """Fetch an article along with its parent instrument and mentioning judgments."""
    article_key = make_node_key(bwb_id, article_number)
    article_doc = store.instrument_articles.get(article_key)
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
        aql, {"article_id": article_id, "relation": RELATION_REFERS_TO_ARTICLE}
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
) -> list[dict[str, Any]]:
    """Return dossiers/documents that introduced, amended, or propose to amend an article.

    Each entry: {dossier_id, dossier_titel, datum, soort, status, samenvatting}.
    """
    from lawgraph.config.settings import RELATION_DEEL_VAN_DOSSIER

    article_key = make_node_key(bwb_id, article_number)
    article_id = f"instrument_articles/{article_key}"

    # Edges pointing TO this article from publications (wijzigt/introduceert/trekt_in)
    # plus edges from the unified collection
    mutation_relations = [
        "WIJZIGT",
        "INTRODUCEERT",
        "TREKT_IN",
        "LICHT_TOE",
        "MENTIONS_ARTICLE",
    ]
    aql = f"""
    FOR edge IN {COLLECTION_EDGES}
        FILTER edge._to == @article_id
        FILTER edge.relation IN @relations
        LET doc = DOCUMENT(edge._from)
        FILTER doc != null
        LET col = SPLIT(edge._from, '/')[0]
        LET dossier = FIRST(
            FOR e2 IN {COLLECTION_EDGES}
                FILTER e2._from == edge._from AND e2.relation == '{RELATION_DEEL_VAN_DOSSIER}'
                LET d = DOCUMENT(e2._to)
                FILTER d != null AND SPLIT(e2._to, '/')[0] == 'kamerstukdossiers'
                LIMIT 1 RETURN d
        )
        SORT edge.status == '{EDGE_STATUS_VOORGESTELD}' ? 0 : 1, doc.props.datum DESC
        RETURN {{
            dossier_id: (dossier != null ? dossier._id : null),
            dossier_nummer: (dossier != null ? dossier.props.kamerstuknummer : null),
            dossier_titel: (dossier != null ? dossier.props.titel : null),
            datum: doc.props.datum,
            soort: doc.props.soort,
            status: edge.status,
            samenvatting: doc.props.display_name,
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
    store: ArangoStore, bwb_id: str, article_number: str
) -> dict[str, Any]:
    """Return in-flux status for an article: boolean + count of open dossiers targeting it."""
    article_key = make_node_key(bwb_id, article_number)
    article_id = f"instrument_articles/{article_key}"

    aql = f"""
    LET voorgesteld_count = LENGTH(
        FOR edge IN {COLLECTION_EDGES}
            FILTER edge._to == @article_id
            FILTER edge.status == '{EDGE_STATUS_VOORGESTELD}'
            RETURN 1
    )
    RETURN {{ in_flux: voorgesteld_count > 0, open_dossier_count: voorgesteld_count }}
    """
    rows = list(store.query(aql, {"article_id": article_id}))
    if rows:
        return rows[0]
    return {"in_flux": False, "open_dossier_count": 0}
