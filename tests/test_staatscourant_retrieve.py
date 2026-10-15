"""``retrieve staatscourant``: each publication stored as it is downloaded, and only what is new
or changed since it was stored."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
import requests

from lawgraph.config.constants import (
    RAW_KIND_STAATSCOURANT_REGELING,
    SOURCE_STAATSCOURANT,
)
from lawgraph.core.time import iso_timestamp
from lawgraph.pipelines.retrieve.staatscourant import StaatscourantRetrievePipeline
from tests.fakes import (
    InMemoryStore,
    external_ids,
    http_error,
    raw_record,
)

pytestmark = pytest.mark.usefixtures("raw_reads")


def _regeling(external_id: str, fetched_at: str) -> dict[str, Any]:
    return raw_record(
        SOURCE_STAATSCOURANT,
        RAW_KIND_STAATSCOURANT_REGELING,
        external_id,
        fetched_at=fetched_at,
    )


def _written(store: InMemoryStore, seeded: list[dict[str, Any]]) -> list[str]:
    """The external ids of the records a run wrote, over what *seeded* the store."""
    return [
        doc["external_id"]
        for doc in store.raw.values()
        if not any(doc is seed for seed in seeded)
    ]


class _Staatscourant:
    def __init__(self, identifiers: list[str], failing: str | None = None) -> None:
        self.identifiers = identifiers
        self.failing = failing
        self.fetched: list[str] = []
        self.modified: dict[str, str] = {}

    def search(self, *, since=None):
        return [
            {"identifier": i, "modified": self.modified.get(i)}
            for i in self.identifiers
        ]

    def fetch_publication_xml(self, identifier: str) -> str:
        self.fetched.append(identifier)
        if identifier == self.failing:
            raise requests.ConnectionError("dropped")
        if identifier == "stcrt-2020-404":
            raise http_error(404)
        return f"<xml>{identifier}</xml>"


def test_staatscourant_stores_each_publication_as_it_is_downloaded() -> None:
    ids = ["stcrt-2020-1", "stcrt-2020-2", "stcrt-2020-3", "stcrt-2020-4"]
    client = _Staatscourant(ids, failing="stcrt-2020-3")
    store = InMemoryStore()
    result = StaatscourantRetrievePipeline(store, client).run()

    # One publication that cannot be downloaded is an error, and the rest is fetched: before,
    # every run ended at the same publication.
    assert external_ids(store) == ["stcrt-2020-1", "stcrt-2020-2", "stcrt-2020-4"]
    assert result.created == 3
    assert result.errors == [
        "1 x download failed (ConnectionError) (first: stcrt-2020-3)"
    ]


def test_staatscourant_rerun_downloads_only_the_rest() -> None:
    """Asked for by name (a gaps run): what an interrupted run stored today is not repeated."""
    ids = ["stcrt-2020-1", "stcrt-2020-2", "stcrt-2020-3"]
    client = _Staatscourant(ids)
    an_hour_ago = iso_timestamp(dt.datetime.now(dt.UTC) - dt.timedelta(hours=1))
    recent = [_regeling(i, an_hour_ago) for i in ["stcrt-2020-1", "stcrt-2020-2"]]
    store = InMemoryStore(raw=recent)
    result = StaatscourantRetrievePipeline(store, client).run(identifiers=ids)

    assert client.fetched == ["stcrt-2020-3"]
    assert _written(store, recent) == ["stcrt-2020-3"] and result.created == 1


def test_staatscourant_leaves_alone_what_was_stored_after_it_last_changed() -> None:
    """A run over a window of two years downloads what is new or changed, not the window."""
    client = _Staatscourant(
        ["stcrt-2020-1", "stcrt-2020-2", "stcrt-2020-3", "stcrt-2020-4"]
    )
    client.modified = {
        "stcrt-2020-1": "2020-03-01",  # stored later: unchanged
        "stcrt-2020-2": "2026-05-01",  # modified after it was stored
        "stcrt-2020-3": "2025-01-10",  # modified on the day it was stored: once more
    }  # and stcrt-2020-4 is not stored at all
    store = InMemoryStore(
        raw=[
            _regeling(i, "2025-01-10T08:00:00Z")
            for i in ["stcrt-2020-1", "stcrt-2020-2", "stcrt-2020-3"]
        ]
    )
    StaatscourantRetrievePipeline(store, client).run()
    assert client.fetched == ["stcrt-2020-2", "stcrt-2020-3", "stcrt-2020-4"]


def test_staatscourant_publication_without_xml_is_skipped() -> None:
    client = _Staatscourant(["stcrt-2020-404", "stcrt-2020-5"])
    store = InMemoryStore()
    result = StaatscourantRetrievePipeline(store, client).run()
    # The publication without XML is remembered as missing (tests/test_missing_documents.py).
    assert external_ids(store) == ["stcrt-2020-404", "stcrt-2020-5"]
    assert (result.created, result.skipped, result.errors) == (1, 1, [])


def test_staatscourant_a_failing_search_is_an_error_not_a_hang() -> None:
    class Down(_Staatscourant):
        def search(self, *, since=None):
            raise requests.ConnectionError("no route")

    result = StaatscourantRetrievePipeline(InMemoryStore(), Down([])).run()
    assert result.created == 0 and "no route" in result.errors[0]
