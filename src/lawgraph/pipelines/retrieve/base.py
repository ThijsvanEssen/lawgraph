from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from lawgraph.db import ArangoStore


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
    def store(self) -> ArangoStore:
        ...

    def fetch(self, *args: object, **kwargs: Any) -> Sequence[RetrieveRecord]:
        ...

    def dump(self, *args: object, **kwargs: Any) -> list[RetrieveRecord]:
        ...


class RetrievePipelineBase(RetrievePipelineProtocol):
    def __init__(self, store: ArangoStore) -> None:
        self._store = store

    def dump(self, *args: object, **kwargs: Any) -> list[RetrieveRecord]:
        """Fetch records and store them in the raw_sources collection."""
        records = list(self.fetch(*args, **kwargs))
        for record in records:
            self._insert(record)
        return records

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
