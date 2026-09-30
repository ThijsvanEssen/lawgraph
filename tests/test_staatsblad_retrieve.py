"""Staatsblad publications the stored BWB toestand XML refers to."""

from __future__ import annotations

from typing import Any

import pytest
import requests

from lawgraph.db.queries import raw as raw_queries
from lawgraph.pipelines.retrieve.staatsblad import StaatsbladRetrievePipeline
from tests.fakes import RawSourcesFake


def _toestand(year: str | None, number: str | None) -> str:
    refs = ""
    if year:
        refs += f"<publicatiejaar>{year}</publicatiejaar>"
    if number:
        refs += f"<publicatienummer>{number}</publicatienummer>"
    return f"<toestand><wetgeving>{refs}</wetgeving></toestand>"


class _Store(RawSourcesFake):
    def __init__(self, rows: list[dict], existing: list[str] | None = None) -> None:
        self.rows = rows
        self.existing = existing or []
        self.stored: list[str] = []

    def insert_raw_source(self, *, external_id: str, **kw: Any) -> None:
        self.stored.append(external_id)


@pytest.fixture(autouse=True)
def _raw_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """The reads of raw_sources, answered from ``_Store.rows`` and ``_Store.existing``."""

    def toestand_payload_refs(store: _Store) -> Any:
        # the real query reads the toestand records only, not the WTI of the regulation
        return iter([r for r in store.rows if r["kind"] == "bwb-toestand-xml"])

    def stored_staatsblad_ids(store: _Store, identifiers: list[str]) -> Any:
        return iter([e for e in store.existing if e in set(identifiers)])

    monkeypatch.setattr(raw_queries, "toestand_payload_refs", toestand_payload_refs)
    monkeypatch.setattr(raw_queries, "stored_staatsblad_ids", stored_staatsblad_ids)
    monkeypatch.setattr(raw_queries, "ids_waiting_for_retry", lambda *_a, **_kw: [])


class _Client:
    def __init__(self, missing: set[str] | None = None) -> None:
        self.fetched: list[str] = []
        self.missing = missing or set()

    def fetch_publication_xml(self, identifier: str) -> str | None:
        self.fetched.append(identifier)
        return None if identifier in self.missing else f"<xml>{identifier}</xml>"


def _row(bwb_id: str, xml: str, kind: str = "bwb-toestand-xml") -> dict:
    return {"bwb_id": bwb_id, "payload_text": xml, "kind": kind}


def _run(rows, existing=None, missing=None):
    store = _Store(rows, existing)
    client = _Client(missing)
    result = StaatsbladRetrievePipeline(store=store, client=client).run_from_bwb_graph(
        store
    )
    return result, store, client


def test_the_publication_a_toestand_refers_to_is_fetched_and_stored() -> None:
    result, store, client = _run([_row("BWBR0004092", _toestand("2012", "79"))])
    assert client.fetched == ["stb-2012-79"]
    assert store.stored == ["stb-2012-79"] and result.created == 1


def test_the_wti_record_of_the_same_regulation_does_not_hide_the_toestand() -> None:
    """The old code kept the last XML per regulation id, which was the WTI (no reference)."""
    rows = [
        _row("BWBR0004092", _toestand("2012", "79")),
        _row(
            "BWBR0004092",
            "<algemene-informatie/>",
            kind="bwb-wti-algemene-informatie-xml",
        ),
    ]
    _, store, client = _run(rows)
    assert client.fetched == ["stb-2012-79"]


def test_toestanden_without_a_reference_are_counted_not_fetched() -> None:
    rows = [
        _row("BWBR0000001", _toestand("2001", "1")),
        _row("BWBR0000002", _toestand(None, None)),
        _row("BWBR0000003", _toestand("2003", None)),
    ]
    result, _, client = _run(rows)
    assert client.fetched == ["stb-2001-1"]
    assert result.skipped == 2


def test_a_publication_several_regulations_refer_to_is_fetched_once() -> None:
    rows = [
        _row("BWBR0000001", _toestand("2001", "1")),
        _row("BWBR0000002", _toestand("2001", "1")),
    ]
    _, store, client = _run(rows)
    assert client.fetched == ["stb-2001-1"]
    assert store.stored == ["stb-2001-1"]


def test_a_publication_that_is_already_stored_is_not_fetched_again() -> None:
    rows = [
        _row("BWBR0000001", _toestand("2001", "1")),
        _row("BWBR0000002", _toestand("2002", "2")),
    ]
    result, store, client = _run(rows, existing=["stb-2001-1"])
    assert client.fetched == ["stb-2002-2"]
    assert result.skipped >= 1


def test_a_publication_without_xml_is_skipped() -> None:
    rows = [
        _row("BWBR0000001", _toestand("2001", "1")),
        _row("BWBR0000002", _toestand("2002", "2")),
    ]
    result, store, _ = _run(rows, missing={"stb-2001-1"})
    assert store.stored == ["stb-2001-1", "stb-2002-2"]  # the first one as missing
    assert result.created == 1 and result.errors == []


def test_a_failing_existence_query_is_not_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(store: _Store, identifiers: list[str]) -> Any:
        raise requests.ConnectionError("database gone")

    monkeypatch.setattr(raw_queries, "stored_staatsblad_ids", broken)
    store = _Store([_row("BWBR0000001", _toestand("2001", "1"))])
    pipeline = StaatsbladRetrievePipeline(store=store, client=_Client())
    try:
        pipeline.run_from_bwb_graph(store)
    except requests.ConnectionError:
        pass
    else:  # pragma: no cover
        raise AssertionError("the failure was swallowed")


def test_a_toestand_without_xml_is_skipped_not_a_crash() -> None:
    result, _, client = _run(
        [{"bwb_id": "BWBR0000001", "payload_text": None, "kind": "bwb-toestand-xml"}]
    )
    assert client.fetched == [] and result.skipped == 1
