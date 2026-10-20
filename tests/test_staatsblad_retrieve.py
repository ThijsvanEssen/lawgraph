"""Staatsblad publications the stored BWB toestand XML refers to."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from typing import Any, cast

import pytest
import requests

from lawgraph.clients.koop_publications import KoopPublicationClient
from lawgraph.config.constants import (
    RAW_KIND_BWB_TOESTAND,
    RAW_KIND_STAATSBLAD_AMVB,
    SOURCE_BWB,
    SOURCE_STAATSBLAD,
)
from lawgraph.db.queries import raw as raw_queries
from lawgraph.pipelines.retrieve import staatsblad
from lawgraph.pipelines.retrieve.base import (
    MAX_FAILURES_IN_A_ROW,
    MISSING_FOR_DAYS,
    missing_record,
    spread_days,
)
from lawgraph.pipelines.retrieve.staatsblad import StaatsbladRetrievePipeline
from tests.asserts import show_items
from tests.fakes import InMemoryStore, external_ids, http_error, raw_record
from tests.optional import present

pytestmark = pytest.mark.usefixtures("raw_reads")


def _ref(year: str | None, number: str | None) -> str | None:
    """The ``staatsblad_ref`` retrieve bwb keeps in the meta of a toestand."""
    return f"stb-{year}-{number}" if year and number else None


def _toestanden(store: InMemoryStore) -> list[dict[str, Any]]:
    return [
        doc
        for doc in store.raw.values()
        if doc["source"] == SOURCE_BWB and doc["kind"] == RAW_KIND_BWB_TOESTAND
    ]


def _toestand_staatsblad_refs(store: InMemoryStore) -> Any:
    return iter(
        {"bwb_id": doc["external_id"], "ref": doc["meta"]["staatsblad_ref"]}
        for doc in _toestanden(store)
        if "staatsblad_ref" in doc.get("meta", {})
    )


def _toestanden_without_staatsblad_ref(store: InMemoryStore) -> Any:
    return iter(
        {**doc, "meta": dict(doc.get("meta", {}))}
        for doc in _toestanden(store)
        if "staatsblad_ref" not in doc.get("meta", {})
    )


def _stored_staatsblad_ids(store: InMemoryStore, identifiers: list[str]) -> Any:
    return iter(
        e
        for e in external_ids(store, RAW_KIND_STAATSBLAD_AMVB)
        if e in set(identifiers)
    )


@pytest.fixture(autouse=True)
def _raw_queries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        raw_queries, "toestand_staatsblad_refs", _toestand_staatsblad_refs
    )
    monkeypatch.setattr(
        raw_queries,
        "toestanden_without_staatsblad_ref",
        _toestanden_without_staatsblad_ref,
    )
    monkeypatch.setattr(raw_queries, "stored_staatsblad_ids", _stored_staatsblad_ids)


class _Client:
    def __init__(self, missing: set[str] | None = None) -> None:
        self.fetched: list[str] = []
        self.missing = missing or set()

    def fetch_publication_xml(self, identifier: str) -> str:
        self.fetched.append(identifier)
        if identifier in self.missing:
            raise http_error(404)
        return f"<xml>{identifier}</xml>"


def _row(bwb_id: str, ref: str | None, kind: str = RAW_KIND_BWB_TOESTAND) -> dict:
    """A stored toestand (or another record of the regulation), without its payload: the
    publication it comes from is in its meta."""
    return raw_record(SOURCE_BWB, kind, bwb_id, meta={"staatsblad_ref": ref})


def _store(rows: list[dict], existing: Iterable[str] = ()) -> InMemoryStore:
    published = [
        raw_record(SOURCE_STAATSBLAD, RAW_KIND_STAATSBLAD_AMVB, e) for e in existing
    ]
    return InMemoryStore(raw=[*rows, *published])


def _stored(store: InMemoryStore) -> list[str]:
    """The publications stored, a missing one included."""
    return [
        d["external_id"] for d in store.raw.values() if d["source"] == SOURCE_STAATSBLAD
    ]


def _run(rows, existing=(), missing=None):
    store = _store(rows, existing)
    client = _Client(missing)
    result = StaatsbladRetrievePipeline(
        store=store, client=cast(KoopPublicationClient, client)
    ).run_from_bwb_graph(store)
    return result, store, client


def test_the_publication_a_toestand_refers_to_is_fetched_and_stored() -> None:
    result, store, client = _run([_row("BWBR0004092", _ref("2012", "79"))])
    assert client.fetched == ["stb-2012-79"]
    assert _stored(store) == ["stb-2012-79"] and result.created == 1


def test_a_toestand_without_the_ref_in_its_meta_is_read_once_and_gets_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A toestand stored before retrieve bwb kept the ref: its XML is read the first run,
    and the ref written into its meta, so the next run reads no payload."""
    xml = (
        "<toestand><wetgeving><publicatie soort='Stb'><publicatiejaar>2012"
        "</publicatiejaar><publicatienr>79</publicatienr></publicatie></wetgeving>"
        "</toestand>"
    )
    rows = [
        _row("BWBR0000001", _ref("2001", "1")),
        raw_record(
            SOURCE_BWB,
            RAW_KIND_BWB_TOESTAND,
            "BWBR0000002",
            payload_text=xml,
            meta={"bwb_id": "BWBR0000002"},
        ),
        raw_record(SOURCE_BWB, RAW_KIND_BWB_TOESTAND, "BWBR0000003", meta={}),
    ]
    result, store, client = _run(rows)
    assert sorted(client.fetched) == ["stb-2001-1", "stb-2012-79"]
    assert result.skipped == 1
    metas = {d["external_id"]: d["meta"] for d in _toestanden(store)}
    assert metas["BWBR0000002"] == {
        "bwb_id": "BWBR0000002",
        "staatsblad_ref": "stb-2012-79",
    }
    assert metas["BWBR0000003"] == {"staatsblad_ref": None}

    def no_parse(xml: str) -> None:
        raise AssertionError("a payload was parsed again")

    monkeypatch.setattr(staatsblad, "staatsblad_ref_from_bwb_xml", no_parse)
    client.fetched.clear()
    again = StaatsbladRetrievePipeline(
        store=store, client=cast(KoopPublicationClient, client)
    ).run_from_bwb_graph(store)
    assert client.fetched == [] and again.skipped == 3


def test_toestanden_without_a_reference_are_counted_not_fetched() -> None:
    rows = [
        _row("BWBR0000001", _ref("2001", "1")),
        _row("BWBR0000002", _ref(None, None)),
        _row("BWBR0000003", _ref("2003", None)),
    ]
    result, _, client = _run(rows)
    assert client.fetched == ["stb-2001-1"]
    assert result.skipped == 2


def test_a_publication_several_regulations_refer_to_is_fetched_once() -> None:
    rows = [
        _row("BWBR0000001", _ref("2001", "1")),
        _row("BWBR0000002", _ref("2001", "1")),
    ]
    _, store, client = _run(rows)
    assert client.fetched == ["stb-2001-1"]
    assert _stored(store) == ["stb-2001-1"]


def test_a_publication_that_is_already_stored_is_not_fetched_again() -> None:
    rows = [
        _row("BWBR0000001", _ref("2001", "1")),
        _row("BWBR0000002", _ref("2002", "2")),
    ]
    result, store, client = _run(rows, existing=["stb-2001-1"])
    assert client.fetched == ["stb-2002-2"]
    assert result.skipped >= 1


def test_a_publication_without_xml_is_skipped() -> None:
    rows = [
        _row("BWBR0000001", _ref("2001", "1")),
        _row("BWBR0000002", _ref("2002", "2")),
    ]
    result, store, _ = _run(rows, missing={"stb-2001-1"})
    assert _stored(store) == ["stb-2001-1", "stb-2002-2"]  # the first one as missing
    assert result.created == 1 and result.errors == []


def test_a_failing_existence_query_is_not_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(store: InMemoryStore, identifiers: list[str]) -> Any:
        raise requests.ConnectionError("database gone")

    monkeypatch.setattr(raw_queries, "stored_staatsblad_ids", broken)
    store = _store([_row("BWBR0000001", _ref("2001", "1"))])
    pipeline = StaatsbladRetrievePipeline(
        store=store, client=cast(KoopPublicationClient, _Client())
    )
    with pytest.raises(requests.ConnectionError):
        pipeline.run_from_bwb_graph(store)


def test_a_toestand_without_a_reference_is_skipped_not_a_crash() -> None:
    result, _, client = _run([_row("BWBR0000001", None)])
    assert client.fetched == [] and result.skipped == 1


class _Failing(_Client):
    """The source answers HTTP 500 for the publications in *broken*."""

    def __init__(self, broken: set[str]) -> None:
        super().__init__()
        self.broken = broken

    def fetch_publication_xml(self, identifier: str) -> str:
        if identifier in self.broken:
            self.fetched.append(identifier)
            raise http_error(500)
        return super().fetch_publication_xml(identifier)


def test_one_publication_the_source_cannot_serve_is_asked_again_next_run() -> None:
    """stb-2015-29246 on web-1: one HTTP 500 no longer fails the step."""
    rows = [
        _row("BWBR0000001", _ref("2015", "29246")),
        _row("BWBR0000002", _ref("2002", "2")),
    ]
    store = _store(rows)
    client = _Failing({"stb-2015-29246"})
    result = StaatsbladRetrievePipeline(
        store=store, client=cast(KoopPublicationClient, client)
    ).run_from_bwb_graph(store)
    assert result.errors == [] and result.created == 1
    # nothing stored for it, so the next run asks for it again
    assert _stored(store) == ["stb-2002-2"]


def test_failed_downloads_apart_are_skips_and_a_run_of_them_fails_the_step() -> None:
    count = MAX_FAILURES_IN_A_ROW + 1
    rows = []
    for n in range(count):  # a broken one, then a served one: the source is not down
        rows.append(_row(f"BWBR{n:07d}", _ref("2015", str(n))))
        rows.append(_row(f"BWBS{n:07d}", _ref("2016", str(n))))
    store = _store(rows)
    client = _Failing({f"stb-2015-{n}" for n in range(count)})
    result = StaatsbladRetrievePipeline(
        store=store, client=cast(KoopPublicationClient, client)
    ).run_from_bwb_graph(store)
    assert (result.created, result.errors) == (count, [])

    down = [_row(f"BWBR{n:07d}", _ref("2015", str(n))) for n in range(60)]
    client = _Failing({f"stb-2015-{n}" for n in range(60)})
    store = _store(down)
    result = StaatsbladRetrievePipeline(
        store=store, client=cast(KoopPublicationClient, client)
    ).run_from_bwb_graph(store)
    assert len(client.fetched) < 2 * MAX_FAILURES_IN_A_ROW
    assert any("seems to be down" in error for error in result.errors), show_items(
        result.errors
    )


def test_the_publications_found_missing_in_one_run_come_due_on_many_days() -> None:
    """web-1, October 2026: 21,446 remembered 404s, all due within six days of each other."""
    ids = [f"stb-1990-{n}" for n in range(2000)]
    spread = {spread_days(i, MISSING_FOR_DAYS) for i in ids}
    assert spread == set(range(MISSING_FOR_DAYS))  # every day of the second month
    # the same publication, the same day, run after run
    assert spread_days("stb-2015-29246", 30) == spread_days("stb-2015-29246", 30)
    record = missing_record("staatsblad", "stb-amvb-xml", "stb-1990-1", spread=True)
    due = dt.datetime.fromisoformat(present(record.meta)["retry_after"])
    days = (due - dt.datetime.now(dt.UTC)).days
    assert MISSING_FOR_DAYS - 1 <= days < 2 * MISSING_FOR_DAYS
