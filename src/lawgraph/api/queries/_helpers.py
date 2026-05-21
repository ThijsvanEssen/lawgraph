"""Private helper functions shared across query sub-modules."""

from __future__ import annotations

from typing import Any, cast

from lawgraph.config.constants import (
    COLLECTION_JUDGMENTS,
    RELATION_MENTIONS_ARTICLE,
    RELATION_PART_OF_INSTRUMENT,
)
from lawgraph.config.settings import COLLECTION_EDGES
from lawgraph.core.models import make_node_key
from lawgraph.db import ArangoStore


def _find_instrument_for_article(
    store: ArangoStore, article_id: str
) -> dict[str, Any] | None:
    aql = f"""
    FOR edge IN {COLLECTION_EDGES}
        FILTER edge._from == @article_id AND edge.relation == @relation
        LIMIT 1
        RETURN DOCUMENT(edge._to)
    """
    for doc in store.query(aql, {"article_id": article_id, "relation": RELATION_PART_OF_INSTRUMENT}):
        return doc
    return None


def _find_judgments_for_article(
    store: ArangoStore, article_id: str
) -> list[dict[str, Any]]:
    aql = f"""
    FOR edge IN {COLLECTION_EDGES}
        FILTER edge._to == @article_id AND edge.relation == @relation
        LET j = DOCUMENT(edge._from)
        FILTER j != null
        RETURN j
    """
    return list(store.query(aql, {"article_id": article_id, "relation": RELATION_MENTIONS_ARTICLE}))


def _load_judgment(store: ArangoStore, ecli: str) -> dict[str, Any] | None:
    key = make_node_key(ecli)
    raw_doc = store.judgments.get(key)
    doc = _ensure_doc(raw_doc)
    if doc is not None:
        return doc
    aql = f"""
    FOR candidate IN {COLLECTION_JUDGMENTS}
        FILTER LOWER(candidate.props.ecli) == @ecli
        LIMIT 1
        RETURN candidate
    """
    for result in store.query(aql, {"ecli": ecli.lower()}):
        return result
    # Fallback for ECHR judgments that have no ECLI — match by appno or external_id.
    aql_alt = f"""
    FOR candidate IN {COLLECTION_JUDGMENTS}
        FILTER candidate.props.appno == @val OR candidate.props.external_id == @val
        LIMIT 1
        RETURN candidate
    """
    for result in store.query(aql_alt, {"val": ecli}):
        return result
    return None


_known_collections: set[str] = set()


def _load_document_by_ref(store: ArangoStore, ref: str | None) -> dict[str, Any] | None:
    if not ref or "/" not in ref:
        return None
    collection_name, key = ref.split("/", 1)
    # Cache the set of known collection names so we don't query the database
    # on every single call (this function is called once per edge in loops).
    if collection_name not in _known_collections:
        if not store.db.has_collection(collection_name):
            return None
        _known_collections.add(collection_name)
    collection = store.db.collection(collection_name)
    raw_doc = collection.get(key)
    return _ensure_doc(raw_doc)


def _extract_span(edge: dict[str, Any]) -> tuple[int | None, int | None, str | None]:
    meta = edge.get("meta")
    if isinstance(meta, dict):
        return (
            _coerce_int(meta.get("start")),
            _coerce_int(meta.get("end")),
            _coerce_text(meta.get("text")),
        )
    return None, None, None


def _extract_confidence(edge: dict[str, Any]) -> float | None:
    raw = edge.get("confidence")
    if isinstance(raw, (int, float)):
        return float(raw)
    meta = edge.get("meta")
    if isinstance(meta, dict):
        conf = meta.get("confidence")
        if isinstance(conf, (int, float)):
            return float(conf)
    return None


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _coerce_text(value: Any) -> str | None:
    if isinstance(value, str):
        trimmed = value.strip()
        return trimmed if trimmed else None
    return None


def _props(doc: dict[str, Any]) -> dict[str, Any]:
    """Return the props sub-dict from a raw ArangoDB document, never None."""
    return doc.get("props") or {}


def _ensure_doc(doc: Any) -> dict[str, Any] | None:
    """Cast a truthy ArangoDB result to dict, returning None for empty/null."""
    if not doc:
        return None
    if not isinstance(doc, dict):
        return None
    return cast(dict[str, Any], doc)


def _resolve_target_from_entry(
    store: ArangoStore, entry: dict[str, Any]
) -> dict[str, Any] | None:
    bwb_id = entry.get("target_bwb_id")
    article_number = entry.get("target_article_number")
    if not bwb_id or not article_number:
        return None
    key = make_node_key(str(bwb_id), str(article_number))
    doc = store.instrument_articles.get(key)
    return _ensure_doc(doc)
