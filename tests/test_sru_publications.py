"""Staatsblad and Staatscourant over the KOOP repository SRU (https://repository.overheid.nl/sru)."""

from __future__ import annotations

import re

import pytest
import requests

from lawgraph.clients._sru import fetch_publication_xml
from lawgraph.clients.base import UnexpectedAnswer
from lawgraph.clients.koop_publications import (
    AMVB,
    MINISTERIAL_REGULATION,
    KoopPublicationClient,
)
from lawgraph.core.identifiers import STB_ID_PATTERN
from tests.asserts import assert_status, show_items
from tests.fakes import ScriptedSession, Sent, http_error
from tests.optional import present
from tests.paths import fixture_text

AMVB_PAGE = fixture_text("sru_staatsblad_amvb_page.xml")  # 1 real record
UNKNOWN_INDEX = fixture_text("sru_unknown_index_diagnostic.xml")


def _page(identifiers: list[str], total: int | None = None) -> str:
    """A result page of real-format records, one per identifier."""
    head, rest = AMVB_PAGE.split("<sru:records>")
    record, tail = rest.split("</sru:records>")
    records = "".join(record.replace("stb-2009-601-b1", i) for i in identifiers)
    text = f"{head}<sru:records>{records}</sru:records>{tail}"
    count = len(identifiers) if total is None else total
    return text.replace(
        "<sru:numberOfRecords>19858</sru:numberOfRecords>",
        f"<sru:numberOfRecords>{count}</sru:numberOfRecords>",
    )


def _client(kind, *responses) -> KoopPublicationClient:
    return KoopPublicationClient(kind, session=ScriptedSession(*responses))


def _sent(client: KoopPublicationClient) -> list[Sent]:
    session = client.session
    assert isinstance(session, ScriptedSession)
    return session.sent


# ── searching ────────────────────────────────────────────────────────────────


def test_a_real_record_is_parsed_with_its_xml_url() -> None:
    records = _client(AMVB, _page(["stb-2009-601-b1"])).search()
    assert records == [
        {
            "identifier": "stb-2009-601-b1",
            "year": "2009",
            "number": "601",
            "title": "Bijlage I Behorende bij artikel 3 van het Uitvoeringsbesluit, kaart 1 t/m 30",
            "content_url": (
                "https://repository.overheid.nl/frbr/officielepublicaties/stb/2009/"
                "stb-2009-601-b1/1/xml/stb-2009-601-b1.xml"
            ),
            "modified": "2014-07-03",
        }
    ]


def test_the_since_filter_uses_an_index_the_repository_knows() -> None:
    client = _client(AMVB, _page(["stb-2009-601"]))
    client.search(since="2026-01-01")
    assert (
        _sent(client)[0]
        .params["query"]
        .startswith("dt.type=AMvB AND dt.modified>=2026-01-01 sortBy")
    )
    client = _client(MINISTERIAL_REGULATION, _page(["stcrt-2026-1"]))
    client.search(since="2026-06-01")
    assert "dt.modified>=2026-06-01" in _sent(client)[0].params["query"]
    assert "dcterms." not in _sent(client)[0].params["query"]


@pytest.mark.parametrize("kind", [AMVB, MINISTERIAL_REGULATION])
def test_an_sru_error_raises_instead_of_an_empty_result(kind) -> None:
    client = _client(kind, UNKNOWN_INDEX)
    with pytest.raises(RuntimeError, match="unknown prefix dcterms"):
        client.search()


# A page a proxy sends with HTTP 200: well-formed, so it parses, and it holds no records.
MAINTENANCE_PAGE = (
    '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Onderhoud</title></head>'
    "<body><p>De dienst is tijdelijk niet beschikbaar.</p></body></html>"
)


@pytest.mark.parametrize("kind", [AMVB, MINISTERIAL_REGULATION])
def test_a_page_that_is_no_sru_response_raises_instead_of_an_empty_result(kind) -> None:
    client = _client(kind, MAINTENANCE_PAGE)
    with pytest.raises(RuntimeError, match="geen SRU-antwoord.*<html>"):
        client.search()


@pytest.mark.parametrize("kind", [AMVB, MINISTERIAL_REGULATION])
def test_a_connection_failure_raises_instead_of_an_empty_result(kind, slept) -> None:
    client = _client(kind, *[requests.ConnectionError("no such host")] * 5)
    with pytest.raises(requests.ConnectionError):
        client.search()


# ── the publication XML ──────────────────────────────────────────────────────


def test_the_xml_is_fetched_from_the_repository_layout() -> None:
    client = _client(AMVB, "<xml/>")
    assert client.fetch_publication_xml("stb-2009-601-b1") == "<xml/>"
    assert _sent(client)[0].url == (
        "https://repository.overheid.nl/frbr/officielepublicaties/stb/2009/"
        "stb-2009-601-b1/1/xml/stb-2009-601-b1.xml"
    )


def test_staatscourant_uses_the_same_layout() -> None:
    client = _client(MINISTERIAL_REGULATION, "<xml/>")
    client.fetch_publication_xml("stcrt-2024-15433")
    assert _sent(client)[0].url.endswith(
        "/stcrt/2024/stcrt-2024-15433/1/xml/stcrt-2024-15433.xml"
    )


@pytest.mark.parametrize("status", [404, 500])
def test_a_failed_request_raises_with_its_status(status: int) -> None:
    client = _client(AMVB, http_error(status))
    with pytest.raises(requests.HTTPError) as raised:
        client.fetch_publication_xml("stb-2009-601")
    assert_status(present(raised.value.response), status)


@pytest.mark.parametrize("identifier", ["stb-2009-601/../x", "not-an-id"])
def test_a_malformed_identifier_is_not_requested(identifier: str) -> None:
    client = _client(AMVB)
    with pytest.raises(UnexpectedAnswer):
        fetch_publication_xml(client, "stb", STB_ID_PATTERN, identifier)
    assert _sent(client) == []


# ── paging ───────────────────────────────────────────────────────────────────


def test_a_page_with_foreign_records_is_not_the_last_page() -> None:
    """The ministeriele-regeling query also returns Staatsblad records; they are dropped
    from the result, but the page was full, so the next one must be requested."""
    first = [f"stcrt-2020-{n}" for n in range(1, 91)] + [
        f"stb-1994-{n}" for n in range(1, 11)
    ]
    second = [f"stcrt-2021-{n}" for n in range(1, 6)]
    client = _client(
        MINISTERIAL_REGULATION, _page(first, total=105), _page(second, total=5)
    )

    records = client.search()

    assert len(records) == 95
    assert len(_sent(client)) == 2


def test_the_next_page_asks_for_the_identifiers_after_the_last_one() -> None:
    """Paging is by key: the service answers 504 for any record from position 10000 on."""
    first = [f"stb-2020-{n:03d}" for n in range(100)]
    client = _client(AMVB, _page(first, total=101), _page(["stb-2021-1"], total=1))

    client.search()

    calls = [sent.params for sent in _sent(client)]
    failing = [c for c in calls if c["startRecord"] != "1"]
    assert not failing, show_items(failing)
    assert calls[0]["query"] == "dt.type=AMvB sortBy dt.identifier/sort.ascending"
    assert calls[1]["query"] == (
        'dt.type=AMvB AND dt.identifier>"stb-2020-099" sortBy dt.identifier/sort.ascending'
    )


def test_a_short_page_ends_the_search() -> None:
    client = _client(AMVB, _page(["stb-2020-1", "stb-2020-2"]))
    assert len(client.search()) == 2
    assert len(_sent(client)) == 1


def test_pages_that_do_not_add_up_to_the_total_raise() -> None:
    client = _client(AMVB, _page(["stb-2020-1"], total=250))
    with pytest.raises(RuntimeError, match="hold 1 records, the service reports 250"):
        client.search()


def test_a_record_of_another_publication_is_left_out_and_counted(caplog) -> None:
    """The Staatscourant query also finds Staatsblad records; a record without a title
    gets one from its number, and the kind's own fields are read."""
    title = re.compile(r"<dcterms:title>[^<]*</dcterms:title>")
    page = title.sub("", _page(["stcrt-2015-134", "stb-1994-1"]))
    with caplog.at_level("INFO"):
        records = _client(MINISTERIAL_REGULATION, page).search()
    assert [r["identifier"] for r in records] == ["stcrt-2015-134"]
    assert records[0]["title"] == "Staatscourant 2015/134"
    assert records[0]["date"] == "2009-12-29"
    assert set(records[0]) == {
        "identifier",
        "year",
        "number",
        "title",
        "content_url",
        "modified",
        "date",
    }
    assert any(
        "1 of another publication left out, such as stb-1994-1" in m
        for m in caplog.messages
    ), show_items(caplog.messages)
