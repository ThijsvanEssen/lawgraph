from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator
from typing import Any

from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, PipelineResult
from lawgraph.core.raw_records import group_by_kind, meta, payload_json, payload_text
from lawgraph.core.time import describe_since, iso_timestamp
from lawgraph.db import ArangoStore, NodeWriter
from lawgraph.pipelines.base import PipelineBase

logger = get_logger(__name__)


class NormalizePipelineBase(PipelineBase, ABC):
    """Base class for pipelines that normalize raw_sources records."""

    def __init__(self, store: ArangoStore) -> None:
        super().__init__(store)

    @abstractmethod
    def fetch_raw(self, *, since: dt.datetime | None = None) -> Any:
        """Fetch raw_sources records relevant for this pipeline."""
        raise NotImplementedError

    @abstractmethod
    def normalize_nodes(self, raw: Any, result: PipelineResult) -> Any:
        """Turn raw data into Node objects and insert them into domain collections."""
        raise NotImplementedError

    @abstractmethod
    def build_edges(self, raw: Any, normalized: Any) -> int:
        """Create edges between normalized nodes; returns number of edges created."""
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

        try:
            raw = self.fetch_raw(since=since)
            normalized = self.normalize_nodes(raw, result)
            edge_count = self.build_edges(raw, normalized)
        except Exception as exc:
            msg = f"{self.__class__.__name__} pipeline failed: {exc}"
            logger.error(msg)
            result.add_error(msg)
            return result

        logger.info(
            "%s normalization pipeline created %d edges.",
            self.__class__.__name__,
            edge_count,
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
        FOR r IN raw_sources
            FILTER r.source == @source
            FILTER r.kind IN @kinds
            {since_filter}
            RETURN r
        """
        bind_vars: dict[str, Any] = {"source": source, "kinds": kinds}
        if since_iso:
            bind_vars["since"] = since_iso
        yield from self.store.query(aql, bind_vars, batch_size=batch_size)

    def _query_raw_sources(
        self,
        *,
        source: str,
        kinds: list[str],
        since: dt.datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Return raw_sources rows for the given source/kinds (optionally filtered by since)."""
        since_iso = iso_timestamp(since)
        bind_vars = {"source": source, "kinds": kinds}

        if since_iso is None:
            aql = """
            FOR r IN raw_sources
                FILTER r.source == @source
                FILTER r.kind IN @kinds
            RETURN r
            """
        else:
            aql = """
            FOR r IN raw_sources
                FILTER r.source == @source
                FILTER r.kind IN @kinds
                FILTER r.fetched_at >= @since
            RETURN r
            """
            bind_vars["since"] = since_iso

        return list(self.store.query(aql, bind_vars=bind_vars))

    def _upsert_nodes(self, nodes: Iterable[Node], *, batch_size: int = 500) -> int:
        """Bulk-upsert *nodes* (see ``NodeWriter``); returns how many were written."""
        with NodeWriter(self.store, batch_size=batch_size) as writer:
            writer.add_all(nodes)
        return writer.written

    # Thin delegates kept for the many subclasses calling ``self._payload_text(...)``
    # etc.; the logic lives in ``lawgraph.core.raw_records``.
    _group_by_kind = staticmethod(group_by_kind)
    _payload_json = staticmethod(payload_json)
    _payload_text = staticmethod(payload_text)
    _meta = staticmethod(meta)
