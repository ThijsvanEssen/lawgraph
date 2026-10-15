"""Staatsblad publications the stored BWB toestand XML refers to."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from typing import Any

import pytest
import requests

from lawgraph.config.constants import (
    RAW_KIND_BWB_TOESTAND,
    RAW_KIND_BWB_WTI_GENERAL,
    RAW_KIND_STB_AMVB,
    SOURCE_BWB,
    SOURCE_STAATSBLAD,
)
from lawgraph.db.queries import raw as raw_queries
from lawgraph.pipelines.retrieve.base import (
    MAX_FAILURES_IN_A_ROW,
    MISSING_FOR_DAYS,
    missing_record,
    spread_days,
)
from lawgraph.pipelines.retrieve.staatsblad import StaatsbladRetrievePipeline
from tests.fakes import InMemoryStore, external_ids, http_error, raw_record

pytestmark = pytest.mark.usefixtures("raw_reads")


def _toestand(year: str | None, number: str | None) -> str:
    refs = ""
    if year:
        refs += f"<publicatiejaar>{year}</publicatiejaar>"
    if number:
        refs += f"<publicatienummer>{number}</publicatienummer>"
    return f"<toestand><wetgeving>{refs}</wetgeving></toestand>"


def _toestand_payload_refs(store: InMemoryStore) -> Any:
    return iter(
        {"bwb_id": doc["external_id"], "payload_text": doc.get("payload_text")}
        for doc in store.raw.values()
        if doc["source"] == SOURCE_BWB and doc["kind"] == RAW_KIND_BWB_TOESTAND
    )


def _stored_staatsblad_ids(store: InMemoryStore, identifiers: list[str]) -> Any:
    return iter(
        e for e in external_ids(store, RAW_KIND_STB_AMVB) if e in set(identifiers)
    )


@pytest.fixture(autouse=True)
def _raw_queries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(raw_queries, "toestand_payload_refs", _toestand_payload_refs)
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


def _row(bwb_id: str, xml: str | None, kind: str = RAW_KIND_BWB_TOESTAND) -> dict:
    return raw_record(SOURCE_BWB, kind, bwb_id, payload_text=xml)


def _store(rows: list[dict], existing: Iterable[str] = ()) -> InMemoryStore:
    published = [raw_record(SOURCE_STAATSBLAD, RAW_KIND_STB_AMVB, e) for e in existing]
    return InMemoryStore(raw=[*rows, *published])


def _stored(store: InMemoryStore) -> list[str]:
    """The publications stored, a missing one included."""
    return [
        d["external_id"] for d in store.raw.values() if d["source"] == SOURCE_STAATSBLAD
    ]


def _run(rows, existing=(), missing=None):
    store = _store(rows, existing)
    client = _Client(missing)
    result = StaatsbladRetrievePipeline(store=store, client=client).run_from_bwb_graph(
        store
    )
    return result, store, client


def test_the_publication_a_toestand_refers_to_is_fetched_and_stored() -> None:
    result, store, client = _run([_row("BWBR0004092", _toestand("2012", "79"))])
    assert client.fetched == ["stb-2012-79"]
    assert _stored(store) == ["stb-2012-79"] and result.created == 1


def test_the_wti_record_of_the_same_regulation_does_not_hide_the_toestand() -> None:
    """The old code kept the last XML per regulation id, which was the WTI (no reference)."""
    rows = [
        _row("BWBR0004092", _toestand("2012", "79")),
        _row(
            "BWBR0004092",
            "<algemene-informatie/>",
            kind=RAW_KIND_BWB_WTI_GENERAL,
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
    assert _stored(store) == ["stb-2001-1"]


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
    assert _stored(store) == ["stb-2001-1", "stb-2002-2"]  # the first one as missing
    assert result.created == 1 and result.errors == []


def test_a_failing_existence_query_is_not_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(store: InMemoryStore, identifiers: list[str]) -> Any:
        raise requests.ConnectionError("database gone")

    monkeypatch.setattr(raw_queries, "stored_staatsblad_ids", broken)
    store = _store([_row("BWBR0000001", _toestand("2001", "1"))])
    pipeline = StaatsbladRetrievePipeline(store=store, client=_Client())
    with pytest.raises(requests.ConnectionError):
        pipeline.run_from_bwb_graph(store)


def test_a_toestand_without_xml_is_skipped_not_a_crash() -> None:
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
        _row("BWBR0000001", _toestand("2015", "29246")),
        _row("BWBR0000002", _toestand("2002", "2")),
    ]
    store = _store(rows)
    client = _Failing({"stb-2015-29246"})
    result = StaatsbladRetrievePipeline(store=store, client=client).run_from_bwb_graph(
        store
    )
    assert result.errors == [] and result.created == 1
    # nothing stored for it, so the next run asks for it again
    assert _stored(store) == ["stb-2002-2"]


def test_failed_downloads_apart_are_skips_and_a_run_of_them_fails_the_step() -> None:
    count = MAX_FAILURES_IN_A_ROW + 1
    rows = []
    for n in range(count):  # a broken one, then a served one: the source is not down
        rows.append(_row(f"BWBR{n:07d}", _toestand("2015", str(n))))
        rows.append(_row(f"BWBS{n:07d}", _toestand("2016", str(n))))
    store = _store(rows)
    client = _Failing({f"stb-2015-{n}" for n in range(count)})
    result = StaatsbladRetrievePipeline(store=store, client=client).run_from_bwb_graph(
        store
    )
    assert (result.created, result.errors) == (count, [])

    down = [_row(f"BWBR{n:07d}", _toestand("2015", str(n))) for n in range(60)]
    client = _Failing({f"stb-2015-{n}" for n in range(60)})
    store = _store(down)
    result = StaatsbladRetrievePipeline(store=store, client=client).run_from_bwb_graph(
        store
    )
    assert len(client.fetched) < 2 * MAX_FAILURES_IN_A_ROW
    assert any("seems to be down" in error for error in result.errors)


def test_the_publications_found_missing_in_one_run_come_due_on_many_days() -> None:
    """web-1, October 2026: 21,446 remembered 404s, all due within six days of each other."""
    ids = [f"stb-1990-{n}" for n in range(2000)]
    spread = {spread_days(i, MISSING_FOR_DAYS) for i in ids}
    assert spread == set(range(MISSING_FOR_DAYS))  # every day of the second month
    # the same publication, the same day, run after run
    assert spread_days("stb-2015-29246", 30) == spread_days("stb-2015-29246", 30)
    record = missing_record("staatsblad", "stb-amvb-xml", "stb-1990-1", spread=True)
    due = dt.datetime.fromisoformat(record.meta["retry_after"])
    days = (due - dt.datetime.now(dt.timezone.utc)).days
    assert MISSING_FOR_DAYS - 1 <= days < 2 * MISSING_FOR_DAYS
