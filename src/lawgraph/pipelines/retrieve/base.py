from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger
from lawgraph.models import PipelineResult

logger = get_logger(__name__)


@dataclass(frozen=True)
class RetrieveRecord:
    source: str
    kind: str
    external_id: str | None
    payload_json: dict | list | None = None
    payload_text: str | None = None
    meta: dict | None = None


@runtime_checkable
class RetrievePipelineProtocol(Protocol):
    @property
    def store(self) -> ArangoStore: ...

    def fetch(self, *args: object, **kwargs: Any) -> Sequence[RetrieveRecord]: ...

    def run(self, *args: object, **kwargs: Any) -> PipelineResult: ...


class RetrievePipelineBase(RetrievePipelineProtocol):
    def __init__(self, store: ArangoStore) -> None:
        self._store = store

    def run(self, *args: object, **kwargs: Any) -> PipelineResult:
        """Fetch records and store them with per-record error handling."""
        result = PipelineResult()
        try:
            records = list(self.fetch(*args, **kwargs))
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

    def fetch(self, *args: object, **kwargs: Any) -> Sequence[RetrieveRecord]:
        """Return the raw source records that should be stored."""
        raise NotImplementedError

    @property
    def store(self) -> ArangoStore:
        return self._store

    def _insert(self, record: RetrieveRecord) -> None:
        self._store.insert_raw_source(
            source=record.source,
            kind=record.kind,
            external_id=record.external_id,
            payload_json=record.payload_json,
            payload_text=record.payload_text,
            meta=record.meta,
        )
