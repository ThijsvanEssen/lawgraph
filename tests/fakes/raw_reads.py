"""The reads of ``db/queries/raw.py``, answered from the ``raw`` of an ``InMemoryStore``."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from itertools import islice
from typing import Any

import pytest

from lawgraph.db.queries import raw as raw_queries
from tests.fakes.store import InMemoryStore


def _records(
    store: InMemoryStore, source: str, kinds: Iterable[str]
) -> list[dict[str, Any]]:
    """The raw records of *source* and *kinds*, in the order of the real queries."""
    return sorted(
        (
            doc
            for doc in store.raw.values()
            if doc["source"] == source and doc["kind"] in kinds
        ),
        key=lambda doc: (doc["kind"], doc["key"]),
    )


def _since(doc: dict[str, Any], moment: str | None) -> bool:
    return moment is None or doc["fetched_at"] >= moment


def _iter_raw_records(
    store: InMemoryStore,
    *,
    source: str,
    kinds: list[str],
    since_iso: str | None,
    batch_size: int,
    chronological: bool = False,
    after: str | None = None,
    limit: int | None = None,
) -> Iterator[dict[str, Any]]:
    records = [
        doc
        for doc in _records(store, source, kinds)
        if _since(doc, since_iso) and (after is None or doc["key"] > after)
    ]
    if chronological:
        records.sort(
            key=lambda doc: (
                (doc.get("meta") or {}).get("bwb_id") or "",
                (doc.get("meta") or {}).get("start_date") or "",
                doc["key"],
            )
        )
    return islice(records, limit)


def _fetched_since(
    store: InMemoryStore, *, source: str, kinds: list[str], since_iso: str
) -> bool:
    return any(_since(doc, since_iso) for doc in _records(store, source, kinds))


def _count_raw_records(store: InMemoryStore, source: str, kinds: list[str]) -> int:
    return len(_records(store, source, kinds))


def _fetch_times(
    store: InMemoryStore, *, source: str, kind: str
) -> Iterator[dict[str, Any]]:
    return iter(
        [
            {"id": doc["external_id"], "at": doc["fetched_at"]}
            for doc in _records(store, source, [kind])
        ]
    )


def _meta_values(
    store: InMemoryStore, *, source: str, kind: str, field: str
) -> Iterator[dict[str, Any]]:
    return iter(
        [
            {"id": doc["external_id"], "value": (doc.get("meta") or {}).get(field)}
            for doc in _records(store, source, [kind])
        ]
    )


def _ids_stored_since(
    store: InMemoryStore, *, source: str, kind: str, cutoff_iso: str | None
) -> Iterator[str]:
    return iter(
        [
            doc["external_id"]
            for doc in _records(store, source, [kind])
            if _since(doc, cutoff_iso)
        ]
    )


def _ids_waiting_for_retry(
    store: InMemoryStore, *, source: str, kind: str, now_iso: str | None
) -> Iterator[str]:
    def waiting(doc: dict[str, Any]) -> bool:
        retry_after = (doc.get("meta") or {}).get("retry_after")
        return retry_after is not None and (now_iso is None or retry_after > now_iso)

    return iter(
        [doc["external_id"] for doc in _records(store, source, [kind]) if waiting(doc)]
    )


def patch_raw_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """The reads of ``db/queries/raw.py`` the retrieve and normalize pipelines share,
    answered from the ``raw`` of an ``InMemoryStore`` (the ``raw_reads`` fixture)."""
    monkeypatch.setattr(raw_queries, "iter_raw_records", _iter_raw_records)
    monkeypatch.setattr(raw_queries, "count_raw_records", _count_raw_records)
    monkeypatch.setattr(raw_queries, "fetched_since", _fetched_since)
    monkeypatch.setattr(raw_queries, "fetch_times", _fetch_times)
    monkeypatch.setattr(raw_queries, "ids_stored_since", _ids_stored_since)
    monkeypatch.setattr(raw_queries, "meta_values", _meta_values)
    monkeypatch.setattr(raw_queries, "ids_waiting_for_retry", _ids_waiting_for_retry)
