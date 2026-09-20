"""Buffered bulk node writes — the node counterpart of ``EdgeWriter``."""

from __future__ import annotations

from typing import Any

from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node
from lawgraph.db.store import ArangoStore

logger = get_logger(__name__)

DEFAULT_BATCH_SIZE = 500


class NodeWriter:
    """Collect nodes and upsert them in bulk, grouped by collection.

    Same merge semantics as ``ArangoStore.insert_or_update`` (props merged,
    labels unioned) but one round-trip per ``batch_size`` nodes. Nodes with the
    same collection and key are de-duplicated (last wins). Because the stored
    document is not returned, keep working from the in-memory node.

        with NodeWriter(self.store) as writer:
            for ...:
                writer.add(node)
    """

    def __init__(
        self, store: ArangoStore, *, batch_size: int = DEFAULT_BATCH_SIZE
    ) -> None:
        self._store = store
        self._batch_size = batch_size
        self._pending: dict[str, dict[str, dict[str, Any]]] = {}
        self._queued = 0
        self.written = 0

    def add(self, node: Node) -> None:
        if node.key is None:
            raise ValueError("Node must have a deterministic key.")
        bucket = self._pending.setdefault(node.collection, {})
        if node.key not in bucket:
            self._queued += 1
        bucket[node.key] = node.to_document()
        if self._queued >= self._batch_size:
            self.flush()

    def add_all(self, nodes: Any) -> None:
        for node in nodes:
            self.add(node)

    def flush(self) -> int:
        """Write everything queued; returns the number of nodes written."""
        written = 0
        for collection, bucket in self._pending.items():
            if not bucket:
                continue
            docs = list(bucket.values())
            try:
                self._store.bulk_insert_or_update_nodes(collection, docs)
            except Exception as exc:
                logger.error(
                    "Node batch upsert failed (%s, %d docs): %s",
                    collection,
                    len(docs),
                    exc,
                )
                raise
            written += len(docs)
        self._pending.clear()
        self._queued = 0
        self.written += written
        return written

    def __enter__(self) -> NodeWriter:
        return self

    def __exit__(self, exc_type: object, *_: object) -> None:
        if exc_type is None:
            self.flush()
