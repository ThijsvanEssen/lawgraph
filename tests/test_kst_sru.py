"""The Kamerstukken of the Tweede Kamer of 1994-1995 to 2007-2008 from the KOOP SRU."""

from __future__ import annotations

from typing import Any

import pytest
import requests

from lawgraph.clients.kamerstuk import KamerstukClient
from lawgraph.core.document_completeness import document_address
from lawgraph.core.kst_documents import kind_and_title
from lawgraph.pipelines.normalize.kst_sru import kst_document
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


def test_the_documents_of_a_real_page_are_parsed() -> None:
    documents = list(_client([PAGE], []).iter_tk_kamerstukken("1997-1998"))

    assert [p["identifier"] for p in documents] == [
        "kst-25877-1",
        "kst-25877-3",
        "kst-25877-4",
        "kst-25877-5",
        "kst-25877-A",
    ]
    mvt = documents[1]
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
    assert documents[0]["numbers"] == ["1", "2"]


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


def test_every_document_of_each_year_becomes_a_raw_record() -> None:
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
def test_documents_are_stored_as_they_come() -> None:
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


# ── normalize ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        (
            "Wet op de inlichtingen- en veiligheidsdiensten 19..; Memorie van toelichting",
            ("Memorie van toelichting", "Memorie van toelichting"),
        ),
        (
            "Wet X; Tweede nota van wijziging",
            ("Nota van wijziging", "Tweede nota van wijziging"),
        ),
        (
            "Wet X; Nota n.a.v. het verslag",
            (
                "Nota n.a.v. het (nader/tweede nader/enz.) verslag",
                "Nota n.a.v. het verslag",
            ),
        ),
        (
            # a dossier with a subtitle: the own title is the part that names a kind
            "Ziekenfondswet; wijz. verlening bijdrage; Amendement over de grens",
            ("Amendement", "Amendement over de grens"),
        ),
        (
            # a kind followed by a title with "; " in it
            'Natuur-educatie; Brief minister met rapport "Evaluatie; eerste jaarrapport"',
            (
                "Brief regering",
                'Brief minister met rapport "Evaluatie; eerste jaarrapport"',
            ),
        ),
        (
            "Huurwet; Gewijzigde motie over de huur",
            ("Motie (gewijzigd/nader)", "Gewijzigde motie over de huur"),
        ),
        ("Huurwet; Verslagen", ("", "Verslagen")),  # no kind on a part of a word
        ("Financiële verantwoording 1997", ("", "Financiële verantwoording 1997")),
    ],
)
def test_the_kind_and_own_title_are_read_from_the_sru_title(title, expected) -> None:
    assert kind_and_title(title) == expected


def _payloads() -> dict[str, dict[str, Any]]:
    documents = _client([PAGE], []).iter_tk_kamerstukken("1997-1998")
    return {p["identifier"]: p for p in documents}


def test_an_sru_record_becomes_a_document_of_the_tweede_kamer_numbered_in_its_dossier() -> (
    None
):
    node = kst_document("kst-25877-3", _payloads()["kst-25877-3"])

    assert node.key == "kst_25877_3" and node.labels == ["TK"]
    props = node.props
    assert props["source"] == "kst" and props["external_id"] == "kst-25877-3"
    assert props["kind"] == "Memorie van toelichting"
    assert props["title"] == "Memorie van toelichting"
    assert (props["dossier_number"], props["sequence"]) == ("25877", 3)
    assert "dossier_suffix" not in props and props["dossier_numbers"] == ["25877"]
    assert props["date"] == "1998-02-18" and props["session_year"] == "1997-1998"
    assert props["subject"].startswith("Regels met betrekking tot de inlichtingen")
    assert props["display_name"] == "Kamerstuk 25877, nr. 3. Memorie van toelichting"
    assert props["pdf_url"].endswith("/kst-25877-3.pdf")
    # where retrieve tk-content looks for its XML
    assert document_address(props) == "kst-25877-3"


def test_a_document_with_two_numbers_is_numbered_by_the_first() -> None:
    bill = kst_document("kst-25877-1", _payloads()["kst-25877-1"])
    assert bill.props["sequence"] == 1 and bill.props["kind"] == "Voorstel van wet"
    joined = kst_document(
        "kst-19326-199", {"numbers": ["199;7f"], "dossier_number": "19326"}
    )
    assert joined.props["sequence"] == 199


def test_a_document_without_an_address_has_no_sequence() -> None:
    advice = kst_document("kst-25877-A", _payloads()["kst-25877-A"])
    assert "sequence" not in advice.props
    assert advice.props["kind"] == "Advies Afdeling advisering Raad van State"
    other = kst_document(
        "kst-20012002-25877-58b", {"numbers": ["58b"], "dossier_number": "25877"}
    )
    assert "sequence" not in other.props


def test_a_reprint_is_the_node_of_the_paper() -> None:
    payload = {"numbers": ["309"], "dossier_number": "17050", "title": "X; Brief"}
    reprint = kst_document("kst-17050-309-h1", payload)
    assert reprint.key == kst_document("kst-17050-309", payload).key == "kst_17050_309"
    assert reprint.props["sequence"] == 309
    assert reprint.props["external_id"] == "kst-17050-309-h1"


def test_a_budget_chapter_is_split_off_the_dossier_number() -> None:
    node = kst_document(
        "kst-26200-VII-5", {"numbers": ["5"], "dossier_number": "26200 VII"}
    )
    props = node.props
    assert (props["dossier_number"], props["dossier_suffix"]) == ("26200", "VII")
    assert props["sequence"] == 5 and props["dossier_numbers"] == ["26200-VII"]


def test_a_part_of_a_series_is_numbered_in_it() -> None:
    node = kst_document(
        "kst-21501-16-186", {"numbers": ["186"], "dossier_number": "21501-16"}
    )
    props = node.props
    assert (props["dossier_number"], props["dossier_suffix"]) == ("21501", "16")
    assert props["sequence"] == 186
    assert document_address(props) == "kst-21501-16-186"
