"""Buffered writes of raw source records — the raw_sources counterpart of ``NodeWriter``."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from lawgraph.core.logging import get_logger
from lawgraph.db.store import ArangoStore

logger = get_logger(__name__)

# A buffer is written when it holds this many records, this many bytes of payload text, or
# when its oldest record has waited this long: whichever comes first. Small records (Tweede
# Kamer JSON, 250 a page) fill it by count, large ones (a toestand XML) by size, and a source
# that needs a request per record by time.
MAX_RECORDS = 500
MAX_BYTES = 8_000_000
MAX_SECONDS = 5.0

Failure = tuple[dict[str, Any], str]


class RawSourceWriter:
    """Collect raw source documents and write them in bulk.

    What a crash can lose is bounded by the buffer: at most ``MAX_RECORDS`` records,
    ``MAX_BYTES`` of text or ``MAX_SECONDS`` of fetching. Leaving the ``with`` block writes
    the buffer, also when it is left by an exception or an interrupt, so a failing source and
    Ctrl-C lose nothing.

        with RawSourceWriter(store, on_flush=count) as writer:
            for ...:
                writer.add(doc)   # a document of ``raw_source_doc``
    """

    def __init__(
        self,
        store: ArangoStore,
        *,
        on_flush: Callable[[list[dict[str, Any]], list[Failure]], None] | None = None,
        max_records: int = MAX_RECORDS,
        max_bytes: int = MAX_BYTES,
        max_seconds: float = MAX_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._store = store
        self._on_flush = on_flush
        self._max_records = max_records
        self._max_bytes = max_bytes
        self._max_seconds = max_seconds
        self._clock = clock
        self._pending: dict[str, dict[str, Any]] = {}
        self._bytes = 0
        self._oldest = 0.0
        self.written = 0

    def __len__(self) -> int:
        return len(self._pending)

    def add(self, doc: dict[str, Any]) -> None:
        """Queue *doc* (same key: last wins) and write the buffer when it is full or old."""
        if not self._pending:
            self._oldest = self._clock()
        self._pending[doc["_key"]] = doc
        self._bytes += len(doc.get("payload_text") or "")
        if (
            len(self._pending) >= self._max_records
            or self._bytes >= self._max_bytes
            or self._clock() - self._oldest >= self._max_seconds
        ):
            self.flush()

    def flush(self) -> None:
        """Write everything queued. A failing write raises; the buffer is kept for a retry."""
        if not self._pending:
            return
        docs = list(self._pending.values())
        failures = self._store.insert_raw_sources(docs)
        self._pending = {}
        self._bytes = 0
        failed_keys = {doc["_key"] for doc, _ in failures}
        stored = [doc for doc in docs if doc["_key"] not in failed_keys]
        self.written += len(stored)
        if self._on_flush:
            self._on_flush(stored, failures)

    def __enter__(self) -> RawSourceWriter:
        return self

    def __exit__(self, exc_type: object, *_: object) -> None:
        try:
            self.flush()
        except Exception as exc:
            if exc_type is None:
                raise
            # Do not let the failing write hide the exception (or interrupt) under way.
            logger.error("The last %d raw records were not stored: %s", len(self), exc)
