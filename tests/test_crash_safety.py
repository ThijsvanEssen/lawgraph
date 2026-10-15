"""A crash, an interrupt or a failing source must not lose what was already fetched."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from typing import Any

import pytest
import requests

from lawgraph.clients import _sru
from lawgraph.clients.base import ATTEMPTS, BaseClient
from lawgraph.clients.eerstekamer import EerstekamerClient
from lawgraph.config.constants import RAW_KIND_STCRT_REGELING, SOURCE_STAATSCOURANT
from lawgraph.core.time import iso_timestamp
from lawgraph.db.queries import raw as raw_queries
from lawgraph.pipelines.retrieve.base import RetrievePipelineBase, RetrieveRecord
from lawgraph.pipelines.retrieve.eerstekamer import EerstekamerRetrievePipeline
from lawgraph.pipelines.retrieve.staatscourant import StaatscourantRetrievePipeline
from lawgraph.pipelines.retrieve.tk import TKRetrievePipeline
from lawgraph.pipelines.retrieve.tk_dossiers import TKDossiersRetrievePipeline
from tests.fakes import (
    InMemoryStore,
    ScriptedSession,
    external_ids,
    http_error,
    raw_record,
)

pytestmark = pytest.mark.usefixtures("raw_reads")


def _regeling(external_id: str, fetched_at: str) -> dict[str, Any]:
    return raw_record(
        SOURCE_STAATSCOURANT,
        RAW_KIND_STCRT_REGELING,
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


def _record(external_id: str) -> RetrieveRecord:
    return RetrieveRecord(
        source="test", kind="test-kind", external_id=external_id, payload_json={}
    )


class _Pipeline(RetrievePipelineBase):
    def __init__(self, store: InMemoryStore, source: Iterator[RetrieveRecord]) -> None:
        super().__init__(store)
        self.source = source

    def fetch(self, **kwargs: Any) -> Iterator[RetrieveRecord]:  # type: ignore[override]
        return self.source


# ── the base class ───────────────────────────────────────────────────────────


def test_a_failure_halfway_keeps_what_was_stored_and_is_an_error() -> None:
    def source() -> Iterator[RetrieveRecord]:
        yield _record("a")
        yield _record("b")
        raise requests.ConnectionError("connection dropped")

    store = InMemoryStore()
    result = _Pipeline(store, source()).run()

    assert external_ids(store) == ["a", "b"]
    assert result.created == 2
    assert len(result.errors) == 1
    assert "after 2 records were stored" in result.errors[0]
    assert "connection dropped" in result.errors[0]


def test_an_interrupt_keeps_what_was_stored() -> None:
    def source() -> Iterator[RetrieveRecord]:
        yield _record("a")
        raise KeyboardInterrupt

    store = InMemoryStore()
    with pytest.raises(KeyboardInterrupt):
        _Pipeline(store, source()).run()
    assert external_ids(store) == ["a"]


def test_a_list_from_fetch_still_works() -> None:
    store = InMemoryStore()
    result = _Pipeline(store, [_record("a"), _record("b")]).run()  # type: ignore[arg-type]
    assert (external_ids(store), result.created) == (["a", "b"], 2)


# ── a re-run after a crash only does the rest ────────────────────────────────


def test_recently_stored_asks_for_the_last_24_hours(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: dict[str, Any] = {}

    def ids_stored_since(store: InMemoryStore, **kwargs: Any) -> list[str]:
        asked.update(kwargs)
        return ["x"]

    monkeypatch.setattr(raw_queries, "ids_stored_since", ids_stored_since)
    done = _Pipeline(InMemoryStore(), iter([]))._recently_stored("src", "kind")
    assert done == {"x"}
    assert asked["source"] == "src" and asked["kind"] == "kind"
    cutoff = dt.datetime.fromisoformat(asked["cutoff_iso"].replace("Z", "+00:00"))
    age = dt.datetime.now(dt.UTC) - cutoff
    assert dt.timedelta(hours=23, minutes=59) < age < dt.timedelta(hours=24, minutes=1)


def test_stored_at_reads_fetched_at_as_utc() -> None:
    store = InMemoryStore(
        raw=[
            raw_record("src", "kind", "a", fetched_at="2026-10-14T08:00:00Z"),
            raw_record("src", "kind", "b", fetched_at="2026-10-14T09:00:00+00:00"),
        ]
    )

    stored = _Pipeline(store, iter([]))._stored_at("src", "kind")

    utc = dt.UTC
    assert stored == {
        "a": dt.datetime(2026, 10, 14, 8, tzinfo=utc),
        "b": dt.datetime(2026, 10, 14, 9, tzinfo=utc),
    }


def test_stored_at_fails_on_a_fetched_at_that_is_no_moment() -> None:
    """``fetched_at`` is always written by ``iso_timestamp``: another value is a bug, not
    a record to fetch again."""
    store = InMemoryStore(
        raw=[
            raw_record("src", "kind", "a", fetched_at="2026-10-14T08:00:00Z"),
            raw_record("src", "kind", "b", fetched_at="yesterday"),
        ]
    )

    with pytest.raises(ValueError) as raised:
        _Pipeline(store, iter([]))._stored_at("src", "kind")

    assert "src kind b" in "\n".join(raised.value.__notes__)


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


# ── the paged SRU searches ───────────────────────────────────────────────────


def _sru_client(pages: list[Any]) -> BaseClient:
    return BaseClient(base_url="https://x.test", session=ScriptedSession(*pages))


def _page(identifiers: list[str], total: int) -> str:
    records = "".join(
        f"<sru:record><sru:recordData><dcterms:identifier>{i}</dcterms:identifier>"
        "</sru:recordData></sru:record>"
        for i in identifiers
    )
    return (
        '<sru:searchRetrieveResponse xmlns:sru="http://docs.oasis-open.org/ns/'
        'search-ws/sruResponse" xmlns:dcterms="http://purl.org/dc/terms/">'
        f"<sru:numberOfRecords>{total}</sru:numberOfRecords><sru:records>{records}"
        "</sru:records></sru:searchRetrieveResponse>"
    )


def _parse(root) -> list[dict[str, Any]]:
    return [{"identifier": i} for i in _identifiers(root)]


def _identifiers(root) -> list[str]:
    return [e.text for e in root.iter() if e.tag.endswith("}identifier") and e.text]


def test_the_records_of_earlier_pages_are_yielded_before_a_later_page_fails(
    slept,
) -> None:
    full = [f"id-{n:03d}" for n in range(100)]
    dropped = [requests.ConnectionError("dropped")] * ATTEMPTS
    client = _sru_client([_page(full, 250), *dropped])
    seen: list[str] = []
    with pytest.raises(requests.ConnectionError):
        for record in _sru.iter_publications(
            client, "https://x.test/sru", query="q", parse=_parse, context="t"
        ):
            seen.append(record["identifier"])
    assert seen == full  # the first page was in hand before the second failed


def test_eerste_kamer_papers_are_stored_page_by_page() -> None:
    class Failing(EerstekamerClient):
        def __init__(self) -> None:
            pass

        def iter_kamerstukken(self, *, since=None, limit=None):
            yield {"identifier": "kst-1", "dossier_number": "1"}
            yield {"identifier": "kst-2", "dossier_number": "1"}
            raise requests.ConnectionError("dropped")

    store = InMemoryStore()
    result = EerstekamerRetrievePipeline(store, Failing()).run()
    assert external_ids(store) == ["kst-1", "kst-2"]
    assert result.created == 2 and result.errors


# ── the Tweede Kamer ─────────────────────────────────────────────────────────


class _TkClient:
    def __init__(self, cases: list[dict], fail_after: int | None = None) -> None:
        self.cases = cases
        self.fail_after = fail_after
        self.top: object = "not called"

    def zaken_modified_since(self, since, *, top=100, **kw):
        self.top = top
        for number, case in enumerate(self.cases):
            if self.fail_after is not None and number >= self.fail_after:
                raise requests.ConnectionError("dropped")
            yield case

    def fetch_documents(self, **kw):
        raise AssertionError("tk-dossiers retrieves the documents, not tk")


def test_tk_cases_are_stored_while_the_pages_come_in() -> None:
    cases = [{"Id": f"zaak-{n}"} for n in range(5)]
    client = _TkClient(cases, fail_after=3)
    store = InMemoryStore()
    result = TKRetrievePipeline(store, client).run(since=dt.datetime(2024, 1, 1))

    assert external_ids(store) == ["zaak-0", "zaak-1", "zaak-2"]
    assert result.created == 3 and "after 3 records" in result.errors[0]


def test_tk_asks_for_every_case_and_for_no_documents() -> None:
    """``$top=0`` answers no records at all; the documents belong to tk-dossiers."""
    client = _TkClient([{"Id": "zaak-1"}])
    store = InMemoryStore()
    TKRetrievePipeline(store, client).run(since=dt.datetime(2024, 1, 1))

    assert client.top is None
    assert external_ids(store) == ["zaak-1"]


class _DossierClient:
    def fetch_dossiers(self, since=None):
        return iter([{"Id": "d1"}, {"Id": "d2"}])

    def fetch_activiteiten(self, since=None):
        yield {"Id": "a1"}
        raise requests.ConnectionError("dropped")

    def __getattr__(self, name):
        return lambda *a, **k: iter([])


def test_tk_dossiers_keep_what_was_stored_when_one_entity_fails() -> None:
    store = InMemoryStore()
    result = TKDossiersRetrievePipeline(store=store, client=_DossierClient()).run(
        since=dt.datetime(2024, 1, 1), skip_members=True
    )
    assert external_ids(store)[:3] == [
        "d1",
        "d2",
        "a1",
    ]  # the activity before the crash is kept
    assert any("Activiteit" in e or "tk-activiteit" in e for e in result.errors)
