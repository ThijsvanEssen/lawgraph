"""Private helper functions shared across query sub-modules."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TypeVar, cast

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_JUDGMENTS,
    RELATION_PART_OF,
    RELATION_REFERS_TO,
)
from lawgraph.core.models import make_node_key, parse_arango_id
from lawgraph.core.qualifiers import Qualifier
from lawgraph.db import ArangoStore
from lawgraph.db._rows import node_doc
from lawgraph.db.schema import NODE_COLLECTIONS


def _find_instrument_for_article(
    store: ArangoStore, article_id: str
) -> dict[str, Any] | None:
    rows = store.query(
        """
        SELECT n.id, n.key, n.type, n.labels, n.props
        FROM edges e JOIN nodes n ON n.id = e.to_id
        WHERE e.from_id = %(article_id)s AND e.relation = %(relation)s
        ORDER BY e.to_id
        LIMIT 1
        """,
        {"article_id": article_id, "relation": RELATION_PART_OF},
    )
    row = next(rows, None)
    return node_doc(row) if row else None


def _find_judgments_for_article(
    store: ArangoStore, article_id: str
) -> list[dict[str, Any]]:
    # What the response shows of a judgment, newest first; the id settles judgments of the
    # same day. A much cited article has thousands of them, and whole judgments (text,
    # paragraphs) are not read for it.
    rows = store.query(
        """
        SELECT json_build_object(
            '_id', j.id,
            '_key', j.key,
            'props', json_build_object(
                'ecli', j.pj_ecli, 'display_name', j.pj_display_name
            )
        )
        FROM edges e JOIN judgments j ON j.id = e.from_id
        WHERE e.to_id = %(article_id)s AND e.relation = %(relation)s
          AND e.from_collection = %(judgments)s
        ORDER BY j.date_eff DESC NULLS LAST, j.id
        """,
        {
            "article_id": article_id,
            "relation": RELATION_REFERS_TO,
            "judgments": COLLECTION_JUDGMENTS,
        },
    )
    return list(rows)


def _load_judgment(store: ArangoStore, ecli: str) -> dict[str, Any] | None:
    """The judgment with this ECLI, or the ECHR decision with this item id or appno.

    Keys are lower case, so the ECLI in any case is one key lookup; an id nobody loaded
    costs two key lookups and one index lookup, not a read of every judgment.
    """
    for key in (make_node_key(ecli), make_node_key("echr", ecli)):
        doc = store.get_document(COLLECTION_JUDGMENTS, key)
        if doc is not None:
            return doc
    # ECHR decisions from before the court gave out ECLIs are asked for by their appno;
    # several can share one, and the key picks the same one every time.
    rows = store.query(
        """
        SELECT id, key, type, labels, props FROM judgments
        WHERE appno = %(appno)s ORDER BY key LIMIT 1
        """,
        {"appno": ecli},
    )
    row = next(rows, None)
    return node_doc(row) if row else None


def _load_document_by_ref(store: ArangoStore, ref: str | None) -> dict[str, Any] | None:
    if not ref or "/" not in ref:
        return None
    collection_name, key = parse_arango_id(ref)
    if collection_name not in NODE_COLLECTIONS:
        return None
    return store.get_document(collection_name, key)


def _extract_span(edge: dict[str, Any]) -> tuple[int | None, int | None, str | None]:
    meta = edge.get("meta")
    if isinstance(meta, dict):
        return (
            _coerce_int(meta.get("start")),
            _coerce_int(meta.get("end")),
            _coerce_text(meta.get("text")),
        )
    return None, None, None


def _extract_qualifier(edge: dict[str, Any]) -> tuple[Qualifier, str | None]:
    """The parts of the cited article the edge names, and how the XML wrote the reference."""
    meta = edge.get("meta")
    if not isinstance(meta, dict):
        return Qualifier(), None
    return Qualifier.from_dict(meta), _coerce_text(meta.get("reference_kind"))


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


props = _props


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
    doc = store.get_document(COLLECTION_ARTICLES, key)
    return _ensure_doc(doc)


T = TypeVar("T")

# The independent queries of one answer (a page and its counts) run side by side, each on a
# connection of the pool: the answer takes as long as the slowest of them.
_TOGETHER = ThreadPoolExecutor(max_workers=4, thread_name_prefix="query")


def run_together(*calls: Callable[[], T]) -> list[T]:
    """The results of *calls*, run at the same time, in their order."""
    return list(_TOGETHER.map(lambda call: call(), calls))
