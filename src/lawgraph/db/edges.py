"""One way to build and write edges — shared by normalize and semantic pipelines.

``make_edge_doc`` is the single edge-document shape (key scheme, ``created_at``,
confidence validation). ``EdgeWriter`` collects edges and writes them with bulk
upserts, so a pipeline pays one database round-trip per batch instead of one
per edge. A writer that remembers what it wrote removes the edges a run no longer
derives (``remove_stale``).
"""

from __future__ import annotations

import datetime as dt
import hashlib
from typing import Any

from lawgraph.config.constants import EDGE_STATUS_CANONIEK
from lawgraph.core.models import PipelineResult
from lawgraph.core.progress import Progress
from lawgraph.db.counting import Store
from lawgraph.db.queries import removals

DEFAULT_BATCH_SIZE = 1000


def edge_key(from_id: str, relation: str, to_id: str) -> str:
    """Deterministic SHA-1 edge key — single scheme used everywhere."""
    return hashlib.sha1(f"{from_id}:{relation}:{to_id}".encode()).hexdigest()


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
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
        "meta": dict(meta or {}),
    }
    if confidence is not None:
        doc["confidence"] = confidence
    return doc


class EdgeWriter:
    """Buffer edges and write them in bulk.

    Usage::

        writer = EdgeWriter(self.store, what=None)
        for ...:
            writer.add(from_id, to_id, RELATION_X, source="...")
        writer.flush()          # or use it as a context manager

    Edges with the same key are de-duplicated inside the buffer (last one
    wins). The buffer is flushed automatically every ``batch_size`` edges, so
    memory stays bounded on large runs. A failing batch raises and stays queued.

    A step that derives its edges in full says ``remembers=True``: the writer then keeps
    the key of every edge it wrote, and its ``remove_stale*`` methods remove the edges of
    the step that it did not write. An edge not written (an id missing) is not kept.
    """

    def __init__(
        self,
        store: Store,
        *,
        what: str | None,
        batch_size: int = DEFAULT_BATCH_SIZE,
        remembers: bool = False,
    ) -> None:
        """*what* names the edges ("VOTED edges"): the writer then reports how far it is.

        For a phase that only writes edges. A loop that tracks its own records (a semantic
        pipeline and its documents) says ``what=None``: one pipeline shows one line. The
        argument has no default, so neither is chosen by forgetting. *remembers*: keep the
        key of every edge written, for ``remove_stale`` (a writer that only writes does not
        pay for it).
        """
        self._store = store
        self._batch_size = batch_size
        self._pending: dict[str, dict[str, Any]] = {}
        self.progress = Progress(what) if what else None
        # relation -> from id -> to id -> edge key, of every edge written
        self._written: dict[str, dict[str, dict[str, str]]] | None = (
            {} if remembers else None
        )
        # relation -> to id -> edge keys: for a relation removed by its end, made when
        # first asked and kept up from then on
        self._into: dict[str, dict[str, set[str]]] = {}
        self.added = 0
        self.created = 0
        self.updated = 0
        self.unchanged = 0

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

    def add_doc(self, doc: dict[str, Any] | None) -> None:
        """Queue a prepared edge document; ``None`` (an edge that could not be made) is not."""
        if doc is None:
            return
        self._pending[doc["_key"]] = doc
        if self._written is not None:
            relation, to_id, key = doc["relation"], doc["_to"], doc["_key"]
            self._written.setdefault(relation, {}).setdefault(doc["_from"], {})[
                to_id
            ] = key
            if relation in self._into:
                self._into[relation].setdefault(to_id, set()).add(key)
        self.added += 1
        if len(self._pending) >= self._batch_size:
            self._write_pending()

    def flush(self) -> tuple[int, int]:
        """Write everything queued and end the progress line; (created, updated) of it."""
        written = self._write_pending()
        if self.progress:
            self.progress.finish()
            self.progress = None
        return written

    def _write_pending(self) -> tuple[int, int]:
        if not self._pending:
            return 0, 0
        batch = list(self._pending.values())
        try:
            created, updated = self._store.bulk_insert_or_update_edges(batch)
        except Exception as exc:
            exc.add_note(
                f"Writing a batch of {len(batch)} edges failed; it stays queued."
            )
            raise
        self._pending.clear()
        self.created += created
        self.updated += updated
        self.unchanged += max(0, len(batch) - created - updated)
        if self.progress:
            self.progress.ok(len(batch))
        return created, updated

    def flush_into(self, result: PipelineResult) -> None:
        """Write what is queued and add what this writer created, updated and found
        unchanged to *result*.

        The one way a pipeline ends its edges: nothing is counted by hand, so nothing can
        be forgotten (the annex edges were written and never counted).
        """
        self.flush()
        result.created += self.created
        result.updated += self.updated
        result.unchanged += self.unchanged
        self.created = self.updated = self.unchanged = 0

    def written(self, relation: str) -> int:
        """How many edges of *relation* this writer wrote, each once."""
        return sum(len(targets) for targets in self._remembered(relation).values())

    def remove_stale(self, relation: str, source: str, from_ids: list[str]) -> int:
        """Remove the *relation* edges of *source* from *from_ids* that this writer did not
        write: the edges of those nodes are derived in full. How many went."""
        return len(self.removed_stale(relation, source, from_ids))

    def removed_stale(
        self, relation: str, source: str, from_ids: list[str]
    ) -> list[tuple[str, str]]:
        """``remove_stale``, answering ``(from_id, to_id)`` of every edge that went."""
        keep = self._keys_from(relation, from_ids)
        return removals.remove_edges_at(
            self._store, "from_id", [relation], from_ids, keep, source=source
        )

    def remove_stale_to(
        self, relations: list[str], source: str, to_ids: list[str]
    ) -> int:
        """Remove the edges of *relations* and *source* into *to_ids* that this writer did
        not write: the edges into those nodes are derived in full. How many went."""
        keep: dict[str, set[str]] = {}
        for relation in relations:
            into = self._keys_into(relation)
            for to_id in to_ids:
                if to_id in into:
                    keep.setdefault(to_id, set()).update(into[to_id])
        removed = removals.remove_edges_at(
            self._store, "to_id", relations, to_ids, keep, source=source
        )
        return len(removed)

    def remove_stale_of_source(self, relation: str, source: str | None) -> int:
        """Remove the *relation* edges of *source* (of any source: None) that this writer
        did not write: the step derives all of them on every run. How many went."""
        keep = [
            key
            for targets in self._remembered(relation).values()
            for key in targets.values()
        ]
        return removals.remove_edges_except(self._store, relation, keep, source=source)

    def _keys_from(self, relation: str, from_ids: list[str]) -> dict[str, set[str]]:
        written = self._remembered(relation)
        return {i: set(written[i].values()) for i in from_ids if i in written}

    def _keys_into(self, relation: str) -> dict[str, set[str]]:
        if relation not in self._into:
            into: dict[str, set[str]] = {}
            for targets in self._remembered(relation).values():
                for to_id, key in targets.items():
                    into.setdefault(to_id, set()).add(key)
            self._into[relation] = into
        return self._into[relation]

    def _remembered(self, relation: str) -> dict[str, dict[str, str]]:
        if self._written is None:
            raise RuntimeError("EdgeWriter(remembers=False) keeps no keys to remove by")
        return self._written.get(relation, {})

    def __enter__(self) -> EdgeWriter:
        return self

    def __exit__(self, exc_type: object, *_: object) -> None:
        if exc_type is None:
            self.flush()
