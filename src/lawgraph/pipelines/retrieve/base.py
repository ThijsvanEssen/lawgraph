from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.db import ArangoStore
from lawgraph.pipelines.base import PipelineBase

logger = get_logger(__name__)


@dataclass(frozen=True)
class RetrieveRecord:
    source: str
    kind: str
    external_id: str | None
    payload_json: dict | list | None = None
    payload_text: str | None = None
    meta: dict | None = None


class RetrievePipelineBase(PipelineBase):
    def __init__(self, store: ArangoStore) -> None:
        super().__init__(store)

    def run(self, **kwargs: Any) -> PipelineResult:
        """Fetch records and store them with per-record error handling."""
        result = PipelineResult()
        try:
            records = list(self.fetch(**kwargs))
        except Exception as exc:
            msg = f"fetch() failed: {exc}"
            logger.error(msg)
            result.add_error(msg)
            return result

        for record in records:
            try:
                self._insert(record)
                result.created += 1
            except Exception as exc:
                msg = f"Failed to store {record.source}/{record.kind}/{record.external_id}: {exc}"
                logger.error(msg)
                result.add_error(msg)
                result.skipped += 1

        return result

    def fetch(self, **kwargs: Any) -> Sequence[RetrieveRecord]:
        """Return the raw source records that should be stored.

        Pipelines that implement complex multi-mode retrieval (BWB, Staatsblad)
        override run() directly instead of implementing fetch(), in which case
        fetch() is never called by the base and should not be overridden.
        """
        return []

    def _insert(self, record: RetrieveRecord) -> None:
        self.store.insert_raw_source(
            source=record.source,
            kind=record.kind,
            external_id=record.external_id,
            payload_json=record.payload_json,
            payload_text=record.payload_text,
            meta=record.meta,
        )
