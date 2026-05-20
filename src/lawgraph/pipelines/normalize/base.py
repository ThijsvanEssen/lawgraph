from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from typing import Any

from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.core.time import describe_since, iso_timestamp
from lawgraph.db import ArangoStore
from lawgraph.pipelines.base import PipelineBase

logger = get_logger(__name__)


class NormalizePipeline(PipelineBase):
    """Base class for pipelines that normalize raw_sources records."""

    def __init__(self, store: ArangoStore) -> None:
        super().__init__(store)

    def fetch_raw(self, *, since: dt.datetime | None = None) -> Any:
        """Fetch raw_sources records relevant for this pipeline."""
        raise NotImplementedError

    def normalize_nodes(self, raw: Any, result: PipelineResult) -> Any:
        """Turn raw data into Node objects and insert them into domain collections."""
        raise NotImplementedError

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

    def _batch_upsert_edges(
        self,
        edge_docs: list[dict],
        *,
        batch_size: int = 500,
    ) -> int:
        """Batch-upsert edge documents; returns the number created."""
        created_total = 0
        for start in range(0, len(edge_docs), batch_size):
            batch = edge_docs[start : start + batch_size]
            try:
                created, _ = self.store.bulk_insert_or_update_edges(batch)
                created_total += created
            except Exception as exc:
                logger.error("Edge batch upsert failed (%d docs): %s", len(batch), exc)
                raise
        return created_total

    @staticmethod
    def _group_by_kind(
        rows: list[dict[str, Any]],
        *,
        kinds: Iterable[str],
    ) -> dict[str, list[dict[str, Any]]]:
        """Group raw_records by their kind, keeping an entry for each requested kind."""
        grouped: dict[str, list[dict[str, Any]]] = {kind: [] for kind in kinds}
        for row in rows:
            kind = row.get("kind")
            if kind in grouped:
                grouped[kind].append(row)
        return grouped

    @staticmethod
    def _payload_json(raw: dict[str, Any]) -> dict[str, Any]:
        payload = raw.get("payload_json")
        if isinstance(payload, dict):
            return payload
        return {}

    @staticmethod
    def _payload_text(raw: dict[str, Any]) -> str | None:
        payload_text = raw.get("payload_text")
        if isinstance(payload_text, str):
            return payload_text
        return None

    @staticmethod
    def _meta(raw: dict[str, Any]) -> dict[str, Any]:
        meta = raw.get("meta")
        if isinstance(meta, dict):
            return meta
        return {}

    @staticmethod
    def _text_contains_keywords(
        text: str | None,
        keywords: Iterable[str],
    ) -> bool:
        if not text:
            return False

        text_lower = text.lower()
        for keyword in keywords:
            lowered = keyword.lower().strip()
            if lowered and lowered in text_lower:
                return True
        return False
