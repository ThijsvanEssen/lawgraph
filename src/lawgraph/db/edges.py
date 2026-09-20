"""One way to build and write edges — shared by normalize and semantic pipelines.

``make_edge_doc`` is the single edge-document shape (key scheme, ``created_at``,
confidence validation). ``EdgeWriter`` collects edges and writes them with bulk
upserts, so a pipeline pays one database round-trip per batch instead of one
per edge.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from lawgraph.config.constants import EDGE_STATUS_CANONIEK
from lawgraph.core.logging import get_logger
from lawgraph.db.store import ArangoStore, edge_key

logger = get_logger(__name__)

DEFAULT_BATCH_SIZE = 1000


def make_edge_doc(
    from_id: str,
    to_id: str,
    relation: str,
    *,
    source: str = "",
    confidence: float | None = None,
    status: str = EDGE_STATUS_CANONIEK,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an edge document with a deterministic key (no database access).

    ``created_at`` is set on insert only; the bulk upsert never overwrites it.
    ``confidence`` is omitted when None (structural edges carry none).
    """
    if confidence is not None and not (0.0 <= confidence <= 1.0):
        raise ValueError(f"confidence must be in [0.0, 1.0], got {confidence}")
    doc: dict[str, Any] = {
        "_key": edge_key(from_id, relation, to_id),
        "_from": from_id,
        "_to": to_id,
        "relation": relation,
        "source": source,
        "status": status,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "meta": dict(meta or {}),
    }
    if confidence is not None:
        doc["confidence"] = confidence
    return doc


class EdgeWriter:
    """Buffer edges and write them in bulk.

    Usage::

        writer = EdgeWriter(self.store)
        for ...:
            writer.add(from_id, to_id, RELATION_X, source="...")
        writer.flush()          # or use it as a context manager

    Edges with the same key are de-duplicated inside the buffer (last one
    wins). The buffer is flushed automatically every ``batch_size`` edges, so
    memory stays bounded on large runs. A failing batch is logged and re-raised.
    """

    def __init__(
        self, store: ArangoStore, *, batch_size: int = DEFAULT_BATCH_SIZE
    ) -> None:
        self._store = store
        self._batch_size = batch_size
        self._pending: dict[str, dict[str, Any]] = {}
        self.added = 0
        self.created = 0
        self.updated = 0

    def add(
        self,
        from_id: str | None,
        to_id: str | None,
        relation: str,
        **fields: Any,
    ) -> bool:
        """Queue an edge; returns False (and queues nothing) if an id is missing."""
        if not from_id or not to_id:
            return False
        self.add_doc(make_edge_doc(from_id, to_id, relation, **fields))
        return True

    def add_doc(self, doc: dict[str, Any]) -> None:
        """Queue a prepared edge document (e.g. from ``make_edge_doc``)."""
        self._pending[doc["_key"]] = doc
        self.added += 1
        if len(self._pending) >= self._batch_size:
            self.flush()

    def flush(self) -> tuple[int, int]:
        """Write everything queued; returns (created, updated) for this flush."""
        if not self._pending:
            return 0, 0
        batch = list(self._pending.values())
        self._pending.clear()
        try:
            created, updated = self._store.bulk_insert_or_update_edges(batch)
        except Exception as exc:
            logger.error("Edge batch upsert failed (%d docs): %s", len(batch), exc)
            raise
        self.created += created
        self.updated += updated
        return created, updated

    def __enter__(self) -> EdgeWriter:
        return self

    def __exit__(self, exc_type: object, *_: object) -> None:
        if exc_type is None:
            self.flush()
