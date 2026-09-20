"""A crash, an interrupt or a failing source must not lose what was already fetched."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
import requests

from lawgraph.clients import _sru
from lawgraph.clients.eerstekamer import EerstekamerClient
from lawgraph.pipelines.retrieve.base import RetrievePipelineBase, RetrieveRecord
from lawgraph.pipelines.retrieve.eerstekamer import EerstekamerRetrievePipeline
from lawgraph.pipelines.retrieve.staatscourant import StaatscourantRetrievePipeline
from lawgraph.pipelines.retrieve.tk import TKRetrievePipeline
from lawgraph.pipelines.retrieve.tk_dossiers import TKDossiersRetrievePipeline
from tests.fakes import RawSourcesFake


class _Store(RawSourcesFake):
    """Records what is stored; ``recent`` is what the last 24 hours already hold."""

    def __init__(self, recent: list[str] | None = None) -> None:
        self.stored: list[str] = []
        self.recent = recent or []

    def query(self, aql: str, bind_vars: dict | None = None) -> list[str]:
        return list(self.recent)

    def insert_raw_source(self, *, external_id: str | None = None, **_kw: Any) -> None:
        self.stored.append(external_id or "")


def _record(external_id: str) -> RetrieveRecord:
    return RetrieveRecord(
        source="test", kind="test-kind", external_id=external_id, payload_json={}
    )


class _Pipeline(RetrievePipelineBase):
    def __init__(self, store: _Store, source: Iterator[RetrieveRecord]) -> None:
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

    store = _Store()
    result = _Pipeline(store, source()).run()

    assert store.stored == ["a", "b"]
    assert result.created == 2
    assert len(result.errors) == 1
    assert "after 2 records were stored" in result.errors[0]
    assert "connection dropped" in result.errors[0]


def test_an_interrupt_keeps_what_was_stored() -> None:
    def source() -> Iterator[RetrieveRecord]:
        yield _record("a")
        raise KeyboardInterrupt

    store = _Store()
    with pytest.raises(KeyboardInterrupt):
        _Pipeline(store, source()).run()
    assert store.stored == ["a"]


def test_a_failing_store_of_one_record_does_not_stop_the_rest() -> None:
    class Flaky(_Store):
        def insert_raw_source(self, *, external_id=None, **kw):
            if external_id == "b":
                raise RuntimeError("write failed")
            super().insert_raw_source(external_id=external_id)

    store = Flaky()
    result = _Pipeline(store, iter([_record("a"), _record("b"), _record("c")])).run()
    assert store.stored == ["a", "c"]
    assert (result.created, result.skipped, len(result.errors)) == (2, 1, 1)


def test_a_list_from_fetch_still_works() -> None:
    store = _Store()
    result = _Pipeline(store, [_record("a"), _record("b")]).run()  # type: ignore[arg-type]
    assert (store.stored, result.created) == (["a", "b"], 2)


# ── a re-run after a crash only does the rest ────────────────────────────────


def test_recently_stored_asks_for_the_last_24_hours() -> None:
    asked: dict[str, Any] = {}

    class Recorder(_Store):
        def query(self, aql, bind_vars=None):
            asked.update(bind_vars or {})
            return ["x"]

    done = _Pipeline(Recorder(), iter([]))._recently_stored("src", "kind")
    assert done == {"x"}
    assert asked["source"] == "src" and asked["kind"] == "kind"
    cutoff = dt.datetime.fromisoformat(asked["cutoff"].replace("Z", "+00:00"))
    age = dt.datetime.now(dt.timezone.utc) - cutoff
    assert dt.timedelta(hours=23, minutes=59) < age < dt.timedelta(hours=24, minutes=1)


class _Staatscourant:
    def __init__(self, identifiers: list[str], failing: str | None = None) -> None:
        self.identifiers = identifiers
        self.failing = failing
        self.fetched: list[str] = []

    def search_ministeriele_regelingen(self, *, since=None):
        return [{"identifier": i} for i in self.identifiers]

    def fetch_publication_xml(self, identifier: str) -> str | None:
        self.fetched.append(identifier)
        if identifier == self.failing:
            raise requests.ConnectionError("dropped")
        return None if identifier == "stcrt-2020-404" else f"<xml>{identifier}</xml>"


def test_staatscourant_stores_each_publication_as_it_is_downloaded() -> None:
    ids = ["stcrt-2020-1", "stcrt-2020-2", "stcrt-2020-3", "stcrt-2020-4"]
    client = _Staatscourant(ids, failing="stcrt-2020-3")
    store = _Store()
    result = StaatscourantRetrievePipeline(store, client).run()

    assert store.stored == ["stcrt-2020-1", "stcrt-2020-2"]  # kept, though #3 crashed
    assert result.created == 2 and "after 2 records" in result.errors[0]


def test_staatscourant_rerun_downloads_only_the_rest() -> None:
    ids = ["stcrt-2020-1", "stcrt-2020-2", "stcrt-2020-3"]
    client = _Staatscourant(ids)
    store = _Store(recent=["stcrt-2020-1", "stcrt-2020-2"])
    result = StaatscourantRetrievePipeline(store, client).run()

    assert client.fetched == ["stcrt-2020-3"]
    assert store.stored == ["stcrt-2020-3"] and result.created == 1


def test_staatscourant_publication_without_xml_is_skipped() -> None:
    client = _Staatscourant(["stcrt-2020-404", "stcrt-2020-5"])
    store = _Store()
    result = StaatscourantRetrievePipeline(store, client).run()
    assert store.stored == ["stcrt-2020-5"] and result.errors == []


def test_staatscourant_a_failing_search_is_an_error_not_a_hang() -> None:
    class Down(_Staatscourant):
        def search_ministeriele_regelingen(self, *, since=None):
            raise requests.ConnectionError("no route")

    result = StaatscourantRetrievePipeline(_Store(), Down([])).run()
    assert result.created == 0 and "no route" in result.errors[0]


# ── the paged SRU searches ───────────────────────────────────────────────────


def _sru_client(pages: list[Any]) -> _sru.BaseClient:
    client = _sru.BaseClient.__new__(_sru.BaseClient)

    def fake_get(url, *, params=None, timeout=30, **_kw):
        page = pages.pop(0)
        if isinstance(page, Exception):
            raise page
        return SimpleNamespace(text=page)

    client._get_raw_absolute_with_retry = fake_get  # type: ignore[method-assign]
    return client


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


def test_the_records_of_earlier_pages_are_yielded_before_a_later_page_fails() -> None:
    full = [f"id-{n:03d}" for n in range(100)]
    client = _sru_client([_page(full, 250), requests.ConnectionError("dropped")])
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

    store = _Store()
    result = EerstekamerRetrievePipeline(store, Failing()).run()
    assert store.stored == ["kst-1", "kst-2"]
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
    store = _Store()
    result = TKRetrievePipeline(store, client).run(since=dt.datetime(2024, 1, 1))

    assert store.stored == ["zaak-0", "zaak-1", "zaak-2"]
    assert result.created == 3 and "after 3 records" in result.errors[0]


def test_tk_asks_for_every_case_and_for_no_documents() -> None:
    """``$top=0`` answers no records at all; the documents belong to tk-dossiers."""
    client = _TkClient([{"Id": "zaak-1"}])
    store = _Store()
    TKRetrievePipeline(store, client).run(since=dt.datetime(2024, 1, 1))

    assert client.top is None
    assert store.stored == ["zaak-1"]


class _DossierClient:
    def fetch_dossiers(self, since=None):
        return iter([{"Id": "d1"}, {"Id": "d2"}])

    def fetch_activiteiten(self, since=None):
        yield {"Id": "a1"}
        raise requests.ConnectionError("dropped")

    def __getattr__(self, name):
        return lambda *a, **k: iter([])


def test_tk_dossiers_keep_what_was_stored_when_one_entity_fails() -> None:
    store = _Store()
    result = TKDossiersRetrievePipeline(store=store, client=_DossierClient()).run(
        since=dt.datetime(2024, 1, 1), skip_members=True
    )
    assert store.stored[:3] == [
        "d1",
        "d2",
        "a1",
    ]  # the activity before the crash is kept
    assert any("Activiteit" in e or "tk-activiteit" in e for e in result.errors)
