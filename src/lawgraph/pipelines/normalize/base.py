from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator
from typing import Any

from lawgraph.config.constants import COLLECTION_RAW_SOURCES
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, PipelineResult
from lawgraph.core.progress import Progress
from lawgraph.core.raw_records import meta, payload_json, payload_text
from lawgraph.core.time import describe_since, iso_timestamp
from lawgraph.db import ArangoStore, CountingStore, NodeWriter
from lawgraph.pipelines.base import PipelineBase

logger = get_logger(__name__)


class RawRecords:
    """The raw records of some kinds, streamed from the database by every ``for`` loop.

    Nothing is kept: a second loop reads them again. For pipelines that walk a large kind
    more than once, where a list would hold every payload for the whole run.
    """

    def __init__(
        self,
        pipeline: NormalizePipelineBase,
        *,
        source: str,
        kinds: list[str],
        since: dt.datetime | None,
        batch_size: int,
    ) -> None:
        self._pipeline = pipeline
        self._options: dict[str, Any] = {
            "source": source,
            "kinds": kinds,
            "since": since,
            "batch_size": batch_size,
        }

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return self._pipeline._iter_raw_sources(**self._options)


class NormalizePipelineBase(PipelineBase, ABC):
    """Base class for pipelines that normalize raw_sources records.

    ``self.store`` is a ``CountingStore``: every node and edge a subclass or its
    helpers upsert through it is counted, and ``run`` reports those counts as
    ``created``/``updated`` on the result. Subclasses only record what the store
    cannot see: ``result.skipped`` and ``result.add_error``.
    """

    store: CountingStore

    def __init__(self, store: ArangoStore) -> None:
        super().__init__(CountingStore(store))

    @abstractmethod
    def fetch_raw(self, *, since: dt.datetime | None = None) -> Any:
        """Fetch raw_sources records relevant for this pipeline."""
        raise NotImplementedError

    @abstractmethod
    def normalize_nodes(self, raw: Any, result: PipelineResult) -> Any:
        """Turn raw data into Node objects and upsert them into domain collections."""
        raise NotImplementedError

    @abstractmethod
    def build_edges(self, raw: Any, normalized: Any) -> None:
        """Upsert the edges between the normalized nodes."""
        raise NotImplementedError

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        """Orchestrate the normalization pipeline steps with logging."""
        result = PipelineResult()
        since_desc = describe_since(since)
        logger.info(
            "Starting %s normalization pipeline (since=%s).",
            self.__class__.__name__,
            since_desc,
        )
        self.store.reset_counts()

        try:
            raw = self.fetch_raw(since=since)
            normalized = self.normalize_nodes(raw, result)
            self.build_edges(raw, normalized)
        except Exception as exc:
            msg = f"{self.__class__.__name__} pipeline failed: {exc}"
            logger.error(msg)
            result.add_error(msg)

        # Also after a failure: what was written before it is in the database.
        writes = self.store.writes
        result.created += writes.created
        result.updated += writes.updated
        logger.info(
            "%s normalization pipeline wrote: %s.",
            self.__class__.__name__,
            writes.describe(),
        )
        return result

    def _iter_raw_sources(
        self,
        *,
        source: str,
        kinds: list[str],
        since: dt.datetime | None = None,
        batch_size: int = 20,
    ) -> Iterator[dict[str, Any]]:
        """Stream raw_sources rows in small batches (for large XML payloads)."""
        since_iso = iso_timestamp(since)
        since_filter = "FILTER r.fetched_at >= @since" if since_iso else ""
        aql = f"""
        FOR r IN {COLLECTION_RAW_SOURCES}
            FILTER r.source == @source
            FILTER r.kind IN @kinds
            {since_filter}
            RETURN r
        """
        bind_vars: dict[str, Any] = {"source": source, "kinds": kinds}
        if since_iso:
            bind_vars["since"] = since_iso
        # The total of a full run comes from the index; with a date every record would
        # have to be read to count it, so an incremental run shows no total and no ETA.
        total = None if since_iso else self._count_raw_sources(source, kinds)
        progress = Progress(f"{'/'.join(kinds)} records", total=total)
        yield from progress.track(
            self.store.query(aql, bind_vars, batch_size=batch_size)
        )

    def _count_raw_sources(self, source: str, kinds: list[str]) -> int | None:
        aql = f"""
        FOR r IN {COLLECTION_RAW_SOURCES}
            FILTER r.source == @source AND r.kind IN @kinds
            COLLECT WITH COUNT INTO n
            RETURN n
        """
        count = next(
            iter(self.store.query(aql, {"source": source, "kinds": kinds})), None
        )
        return count if isinstance(count, int) else None

    def _upsert_nodes(self, nodes: Iterable[Node], *, batch_size: int = 500) -> int:
        """Bulk-upsert *nodes* (see ``NodeWriter``); returns how many were written."""
        with NodeWriter(self.store, batch_size=batch_size) as writer:
            writer.add_all(nodes)
        return writer.written

    # Thin delegates kept for the many subclasses calling ``self._payload_text(...)``
    # etc.; the logic lives in ``lawgraph.core.raw_records``.
    _payload_json = staticmethod(payload_json)
    _payload_text = staticmethod(payload_text)
    _meta = staticmethod(meta)
