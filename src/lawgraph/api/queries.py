"""Read-only query helpers used by the FastAPI layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Literal, cast

from lawgraph.config.settings import (
    COLLECTION_JUDGMENTS,
    RELATION_MENTIONS_ARTICLE,
    RELATION_PART_OF_INSTRUMENT,
)
from lawgraph.db import ArangoStore
from lawgraph.models import make_node_key
from arango.collection import StandardCollection


_ALLOWED_NODE_COLLECTIONS = {
    "instruments",
    "instrument_articles",
    "judgments",
    "procedures",
    "publications",
    "topics",
}


DIRECTION_BINDINGS: tuple[tuple[Literal["outbound"], str], tuple[Literal["inbound"], str]] = (
    ("outbound", "_from"),
    ("inbound", "_to"),
)

@dataclass
class ArticleDetailData:
    article: dict[str, Any]
    instrument: dict[str, Any] | None
    judgments: list[dict[str, Any]]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class JudgmentArticleRelation:
    article: dict[str, Any]
    instrument: dict[str, Any] | None


@dataclass
class JudgmentDetailData:
    judgment: dict[str, Any]
    articles: list[JudgmentArticleRelation]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class NeighborEntry:
    doc: dict[str, Any]
    relation: str | None
    direction: Literal["outbound", "inbound"]
    confidence: float | None


@dataclass
class NodeGraphData:
    node: dict[str, Any]
    strict_neighbors: list[NeighborEntry]
    semantic_neighbors: list[NeighborEntry]


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


def get_judgment_with_relations(store: ArangoStore, ecli: str) -> JudgmentDetailData:
    """Fetch a judgment and related articles via semantic edges."""
    judgment_doc = _load_judgment(store, ecli)
    if judgment_doc is None:
        raise ValueError("judgment not found")

    article_relations: list[JudgmentArticleRelation] = []
    edges = _iter_edges(
        store.edges_semantic,
        {"_from": judgment_doc["_id"], "relation": RELATION_MENTIONS_ARTICLE},
    )
    for edge in edges:
        article_doc = _load_document_by_ref(store, edge.get("_to"))
        if not article_doc:
            continue
        instrument_doc = _find_instrument_for_article(
            store, article_doc["_id"])
        article_relations.append(JudgmentArticleRelation(
            article=article_doc, instrument=instrument_doc))

    metadata = {"article_count": len(article_relations)}
    return JudgmentDetailData(
        judgment=judgment_doc,
        articles=article_relations,
        metadata=metadata,
    )


def get_node_with_neighbors(
    store: ArangoStore,
    collection: str,
    key: str,
) -> NodeGraphData:
    """Retrieve a node together with strict/semantic neighbors."""
    if collection not in _ALLOWED_NODE_COLLECTIONS:
        raise ValueError("unsupported collection")

    if not store.db.has_collection(collection):
        raise ValueError(f"collection {collection} not found")

    coll = store.db.collection(collection)
    raw_node = coll.get(key)
    if raw_node is None:
        raise ValueError("node not found")
    node_doc = _ensure_doc(raw_node)
    if node_doc is None:
        raise ValueError("node not found")

    strict_neighbors = _collect_neighbors(
        store, node_doc["_id"], store.edges_strict)
    semantic_neighbors = _collect_neighbors(
        store, node_doc["_id"], store.edges_semantic)

    return NodeGraphData(
        node=node_doc,
        strict_neighbors=strict_neighbors,
        semantic_neighbors=semantic_neighbors,
    )


def _find_instrument_for_article(
    store: ArangoStore,
    article_id: str,
) -> dict[str, Any] | None:
    edges = _iter_edges(
        store.edges_strict,
        {"_from": article_id, "relation": RELATION_PART_OF_INSTRUMENT},
    )
    for edge in edges:
        return _load_document_by_ref(store, edge.get("_to"))
    return None


def _find_judgments_for_article(
    store: ArangoStore,
    article_id: str,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    edges = _iter_edges(
        store.edges_semantic,
        {"_to": article_id, "relation": RELATION_MENTIONS_ARTICLE},
    )
    for edge in edges:
        judgment_doc = _load_document_by_ref(store, edge.get("_from"))
        if judgment_doc:
            results.append(judgment_doc)
    return results


def _load_judgment(store: ArangoStore, ecli: str) -> dict[str, Any] | None:
    key = make_node_key(ecli)
    raw_doc = store.judgments.get(key)
    doc = _ensure_doc(raw_doc)
    if doc is not None:
        return doc

    query = """
        FOR candidate IN {}
            FILTER candidate.props.ecli == @ecli
            LIMIT 1
            RETURN candidate
    """.format(COLLECTION_JUDGMENTS)
    for result in store.query(query, {"ecli": ecli}):
        return result
    return None


def _load_document_by_ref(store: ArangoStore, ref: str | None) -> dict[str, Any] | None:
    if not ref or "/" not in ref:
        return None
    collection_name, key = ref.split("/", 1)
    if not store.db.has_collection(collection_name):
        return None
    collection = store.db.collection(collection_name)
    raw_doc = collection.get(key)
    return _ensure_doc(raw_doc)


def _iter_edges(
    collection: StandardCollection,
    filter_doc: dict[str, Any],
) -> Iterable[dict[str, Any]]:
    cursor = collection.find(filter_doc)
    return cast(Iterable[dict[str, Any]], cursor)


def _ensure_doc(doc: Any | None) -> dict[str, Any] | None:
    if not doc:
        return None
    return cast(dict[str, Any], doc)


def _collect_neighbors(
    store: ArangoStore,
    node_id: str,
    collection: StandardCollection,
) -> list[NeighborEntry]:
    neighbors: list[NeighborEntry] = []
    for direction, field in DIRECTION_BINDINGS:
        edges = _iter_edges(collection, {field: node_id})
        for edge in edges:
            neighbor_ref = edge.get("_to" if field == "_from" else "_from")
            neighbor_doc = _load_document_by_ref(store, neighbor_ref)
            if not neighbor_doc:
                continue
            neighbors.append(
                NeighborEntry(
                    doc=neighbor_doc,
                    relation=edge.get("relation"),
                    direction=direction,
                    confidence=_extract_confidence(edge),
                )
            )
    return neighbors


def _extract_confidence(edge: dict[str, Any]) -> float | None:
    meta = edge.get("meta")
    if isinstance(meta, dict):
        confidence = meta.get("confidence")
        if isinstance(confidence, (int, float)):
            return float(confidence)
    return None
