"""Private helper functions shared across query sub-modules."""

from __future__ import annotations

import contextvars
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, wait
from typing import Any, TypeVar, cast

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_JUDGMENTS,
    RELATION_PART_OF,
    RELATION_REFERS_TO,
)
from lawgraph.core.documents import CHAMBERS
from lawgraph.core.models import make_node_key, parse_node_id
from lawgraph.core.qualifiers import Qualifier
from lawgraph.db import GraphStore
from lawgraph.db._rows import node_doc
from lawgraph.db.schema import NODE_COLLECTIONS
from lawgraph.db.store import ReadTimedOut, read_time_left


def _find_instrument_for_article(
    store: GraphStore, article_id: str
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


def _count_judgments_for_article(store: GraphStore, article_id: str) -> int:
    """How many judgments cite the article: counted on the index of the edges alone (a much
    cited article has thousands, ``/cited-by`` pages them)."""
    return int(
        next(
            store.query(
                """
                SELECT count(*)::int FROM edges e
                WHERE e.to_id = %(article_id)s AND e.relation = %(relation)s
                  AND e.from_collection = %(judgments)s
                """,
                {
                    "article_id": article_id,
                    "relation": RELATION_REFERS_TO,
                    "judgments": COLLECTION_JUDGMENTS,
                },
            ),
            0,
        )
    )


def _load_judgment(store: GraphStore, ecli: str) -> dict[str, Any] | None:
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


def _load_document_by_ref(store: GraphStore, ref: str | None) -> dict[str, Any] | None:
    if not ref or "/" not in ref:
        return None
    collection_name, key = parse_node_id(ref)
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
    store: GraphStore, entry: dict[str, Any]
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
    return side_by_side(_TOGETHER, list(calls))


def side_by_side(pool: ThreadPoolExecutor, calls: list[Callable[[], T]]) -> list[T]:
    """The results of *calls*, run on the threads of *pool*, in their order.

    Each call runs in a copy of the caller's context, so the deadline of a request
    (``store.read_time_left``) holds in the thread too; the caller waits for them no longer
    than that deadline (``ReadTimedOut``: a 503, while the calls end at their own statement
    timeout). The pool is shared by every request: a call for which no thread of it is
    free runs in the caller's own thread, so that a request never queues behind the slow
    queries of others, and a call from a thread of *pool* itself runs there (waiting for
    the others, it could wait for itself)."""
    prefix = getattr(pool, "_thread_name_prefix", "")
    if prefix and threading.current_thread().name.startswith(prefix):
        return [call() for call in calls]
    free = _free_threads(pool)
    futures: list[Future[T] | None] = []
    for call in calls:
        if free.acquire(blocking=False):
            futures.append(
                pool.submit(contextvars.copy_context().run, _releasing, free, call)
            )
        else:
            futures.append(None)
    results: dict[int, T] = {
        n: call()
        for n, (call, future) in enumerate(zip(calls, futures, strict=True))
        if future is None
    }
    submitted = [future for future in futures if future is not None]
    done, waiting = wait(submitted, timeout=read_time_left())
    if waiting:
        raise ReadTimedOut(
            "The request ran past its deadline waiting for queries run side by side."
        )
    return [
        results[n] if future is None else future.result()
        for n, future in enumerate(futures)
    ]


# The threads of each shared pool not running a call now (``side_by_side``).
_free: dict[int, threading.BoundedSemaphore] = {}
_free_lock = threading.Lock()


def _free_threads(pool: ThreadPoolExecutor) -> threading.BoundedSemaphore:
    with _free_lock:
        if id(pool) not in _free:
            _free[id(pool)] = threading.BoundedSemaphore(pool._max_workers)
        return _free[id(pool)]


def _releasing(free: threading.BoundedSemaphore, call: Callable[[], T]) -> T:
    try:
        return call()
    finally:
        free.release()


def chamber_sql(alias: str) -> str:
    """``core.documents.chamber_of`` in SQL, over the labels of the row *alias*."""
    whens = " ".join(f"WHEN '{c}' = ANY({alias}.labels) THEN '{c}'" for c in CHAMBERS)
    return f"CASE {whens} END"
