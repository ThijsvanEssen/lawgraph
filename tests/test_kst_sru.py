"""The Kamerstukken of the Tweede Kamer of 1994-1995 to 2007-2008 from the KOOP SRU."""

from __future__ import annotations

from typing import Any

import pytest
import requests

from lawgraph.clients.kamerstuk import KamerstukClient
from lawgraph.pipelines.retrieve.kst_sru import KstSruRetrievePipeline, session_years
from tests.fakes import InMemoryStore, ScriptedSession, external_ids
from tests.paths import fixture_text

# w.dossiernummer==25877 in 1997-1998: kst-25877-1, -3, -4, -5 and -A (total 5)
PAGE = fixture_text("sru_kst_tk_25877_page.xml")
EMPTY = (
    PAGE.replace(
        "<sru:numberOfRecords>5</sru:numberOfRecords>",
        "<sru:numberOfRecords>0</sru:numberOfRecords>",
    ).split("<sru:records>")[0]
    + "</sru:searchRetrieveResponse>"
)


def _client(responses: list[Any], calls: list[dict]) -> KamerstukClient:
    return KamerstukClient(session=ScriptedSession(*responses, asked=calls))


# ── the client ───────────────────────────────────────────────────────────────


def test_the_papers_of_a_real_page_are_parsed() -> None:
    papers = list(_client([PAGE], []).iter_tk_kamerstukken("1997-1998"))

    assert [p["identifier"] for p in papers] == [
        "kst-25877-1",
        "kst-25877-3",
        "kst-25877-4",
        "kst-25877-5",
        "kst-25877-A",
    ]
    mvt = papers[1]
    assert mvt["title"].endswith("; Memorie van toelichting")
    assert mvt["numbers"] == ["3"]
    assert mvt["dossier_number"] == "25877" and mvt["dossier_numbers"] == ["25877"]
    assert mvt["session_year"] == "1997-1998"
    assert mvt["date"] == "1998-02-18"
    assert mvt["dossier_title"].startswith("Regels met betrekking tot de inlichtingen")
    assert mvt["url"] == "https://zoek.officielebekendmakingen.nl/kst-25877-3.html"
    assert mvt["xml_url"].endswith("/kst/25877/kst-25877-3/1/xml/kst-25877-3.xml")
    assert mvt["pdf_url"].endswith("/kst-25877-3/1/pdf/kst-25877-3.pdf")
    # a bill and its royal message are one publication
    assert papers[0]["numbers"] == ["1", "2"]


def test_only_tweede_kamer_kamerstukken_of_the_session_year_are_asked_for() -> None:
    calls: list[dict] = []
    list(_client([PAGE], calls).iter_tk_kamerstukken("1997-1998", since="2026-09-01"))
    query = calls[0]["query"]
    assert 'dt.creator=="Tweede Kamer der Staten-Generaal"' in query
    assert "w.publicatienaam==Kamerstuk" in query and "dt.type==Kamerstuk" in query
    assert "w.vergaderjaar==1997-1998" in query
    assert "dt.modified>=2026-09-01" in query


def test_session_years() -> None:
    years = session_years()
    assert years[0] == "1994-1995" and years[-1] == "2007-2008" and len(years) == 14


# ── retrieve ─────────────────────────────────────────────────────────────────


def test_every_paper_of_each_year_becomes_a_raw_record() -> None:
    calls: list[dict] = []
    store = InMemoryStore()
    pipeline = KstSruRetrievePipeline(store, _client([EMPTY, PAGE], calls))
    result = pipeline.run(years=["1996-1997", "1997-1998"])

    assert (result.created, result.errors) == (5, [])
    assert "w.vergaderjaar==1996-1997" in calls[0]["query"]
    assert "w.vergaderjaar==1997-1998" in calls[1]["query"]
    record = next(r for r in store.raw.values() if r["external_id"] == "kst-25877-3")
    assert record["source"] == "kst" and record["kind"] == "kst-sru-json"
    assert record["payload_json"]["numbers"] == ["3"]
    assert record["meta"] == {
        "session_year": "1997-1998",
        "dossier_number": "25877",
        "modified": "2014-07-10",
    }


def test_limit_counts_over_the_years() -> None:
    calls: list[dict] = []
    store = InMemoryStore()
    pipeline = KstSruRetrievePipeline(store, _client([PAGE], calls))
    result = pipeline.run(years=["1997-1998", "1998-1999"], limit=3)

    assert result.created == 3
    assert len(calls) == 1  # the second year is not asked for


@pytest.mark.usefixtures("raw_reads")
def test_papers_are_stored_as_they_come() -> None:
    class Failing(KamerstukClient):
        def __init__(self) -> None:
            pass

        def iter_tk_kamerstukken(self, session_year, *, since=None, limit=None):
            yield {"identifier": "kst-1-1", "dossier_number": "1"}
            raise requests.ConnectionError("dropped")

    store = InMemoryStore()
    result = KstSruRetrievePipeline(store, Failing()).run(years=["1997-1998"])
    assert external_ids(store) == ["kst-1-1"]
    assert result.created == 1 and result.errors
