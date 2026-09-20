"""Staatsblad and Staatscourant over the KOOP repository SRU (https://repository.overheid.nl/sru)."""

from __future__ import annotations

import pathlib
from types import SimpleNamespace

import pytest
import requests

from lawgraph.clients import staatsblad as staatsblad_module
from lawgraph.clients import staatscourant as staatscourant_module
from lawgraph.clients._sru import fetch_publication_xml
from lawgraph.clients.staatsblad import StaatsbladClient
from lawgraph.clients.staatscourant import StaatscourantClient
from lawgraph.core.identifiers import STB_ID_PATTERN
from tests.fakes import FakeResponse

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
AMVB_PAGE = (FIXTURES / "sru_staatsblad_amvb_page.xml").read_text()  # 1 real record
UNKNOWN_INDEX = (FIXTURES / "sru_unknown_index_diagnostic.xml").read_text()


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


def _http_error(status: int) -> requests.HTTPError:
    return requests.HTTPError(str(status), response=SimpleNamespace(status_code=status))


def _client(cls, responses: list, calls: list[dict]):
    client = cls.__new__(cls)  # no HTTP session needed
    client.base_url = "https://repository.overheid.nl"

    def fake_get(url, *, params=None, timeout=30, **_kw):
        calls.append({"url": url, "params": params})
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return FakeResponse(response)

    client._get_raw_absolute_with_retry = fake_get
    return client


# ── searching ────────────────────────────────────────────────────────────────


def test_a_real_record_is_parsed_with_its_xml_url() -> None:
    records = _client(StaatsbladClient, [_page(["stb-2009-601-b1"])], []).search_amvbs()
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
    calls: list[dict] = []
    _client(StaatsbladClient, [_page(["stb-2009-601"])], calls).search_amvbs(
        since="2026-01-01"
    )
    assert calls[0]["params"]["query"].startswith(
        "dt.type=AMvB AND dt.modified>=2026-01-01 sortBy"
    )
    calls.clear()
    _client(
        StaatscourantClient, [_page(["stcrt-2026-1"])], calls
    ).search_ministeriele_regelingen(since="2026-06-01")
    assert "dt.modified>=2026-06-01" in calls[0]["params"]["query"]
    assert "dcterms." not in calls[0]["params"]["query"]


@pytest.mark.parametrize(
    ("cls", "search"),
    [
        (StaatsbladClient, "search_amvbs"),
        (StaatscourantClient, "search_ministeriele_regelingen"),
    ],
)
def test_an_sru_error_raises_instead_of_an_empty_result(cls, search) -> None:
    client = _client(cls, [UNKNOWN_INDEX], [])
    with pytest.raises(RuntimeError, match="unknown prefix dcterms"):
        getattr(client, search)()


@pytest.mark.parametrize(
    ("cls", "search"),
    [
        (StaatsbladClient, "search_amvbs"),
        (StaatscourantClient, "search_ministeriele_regelingen"),
    ],
)
def test_a_connection_failure_raises_instead_of_an_empty_result(cls, search) -> None:
    client = _client(cls, [requests.ConnectionError("no such host")], [])
    with pytest.raises(requests.ConnectionError):
        getattr(client, search)()


def test_the_default_endpoints_are_the_repository() -> None:
    assert (
        staatsblad_module.STAATSBLAD_SRU_ENDPOINT
        == "https://repository.overheid.nl/sru"
    )
    assert (
        staatscourant_module.STAATSCOURANT_SRU_ENDPOINT
        == "https://repository.overheid.nl/sru"
    )


# ── the publication XML ──────────────────────────────────────────────────────


def test_the_xml_is_fetched_from_the_repository_layout() -> None:
    calls: list[dict] = []
    client = _client(StaatsbladClient, ["<xml/>"], calls)
    assert client.fetch_publication_xml("stb-2009-601-b1") == "<xml/>"
    assert calls[0]["url"] == (
        "https://repository.overheid.nl/frbr/officielepublicaties/stb/2009/"
        "stb-2009-601-b1/1/xml/stb-2009-601-b1.xml"
    )


def test_staatscourant_uses_the_same_layout() -> None:
    calls: list[dict] = []
    client = _client(StaatscourantClient, ["<xml/>"], calls)
    client.fetch_publication_xml("stcrt-2024-15433")
    assert calls[0]["url"].endswith(
        "/stcrt/2024/stcrt-2024-15433/1/xml/stcrt-2024-15433.xml"
    )


def test_a_missing_xml_is_none_but_other_failures_raise() -> None:
    assert (
        _client(StaatsbladClient, [_http_error(404)], []).fetch_publication_xml(
            "stb-2009-601"
        )
        is None
    )
    with pytest.raises(requests.HTTPError):
        _client(StaatsbladClient, [_http_error(500)], []).fetch_publication_xml(
            "stb-2009-601"
        )


def test_a_malformed_identifier_is_not_requested() -> None:
    calls: list[dict] = []
    client = _client(StaatsbladClient, [], calls)
    assert (
        fetch_publication_xml(client, "stb", STB_ID_PATTERN, "stb-2009-601/../x")
        is None
    )
    assert fetch_publication_xml(client, "stb", STB_ID_PATTERN, "not-an-id") is None
    assert calls == []


# ── paging ───────────────────────────────────────────────────────────────────


def test_a_page_with_foreign_records_is_not_the_last_page() -> None:
    """The ministeriele-regeling query also returns Staatsblad records; they are dropped
    from the result, but the page was full, so the next one must be requested."""
    first = [f"stcrt-2020-{n}" for n in range(1, 91)] + [
        f"stb-1994-{n}" for n in range(1, 11)
    ]
    second = [f"stcrt-2021-{n}" for n in range(1, 6)]
    calls: list[dict] = []
    client = _client(
        StaatscourantClient, [_page(first, total=105), _page(second, total=5)], calls
    )

    records = client.search_ministeriele_regelingen()

    assert len(records) == 95
    assert len(calls) == 2


def test_the_next_page_asks_for_the_identifiers_after_the_last_one() -> None:
    """Paging is by key: the service answers 504 for any record from position 10000 on."""
    first = [f"stb-2020-{n:03d}" for n in range(100)]
    calls: list[dict] = []
    client = _client(
        StaatsbladClient,
        [_page(first, total=101), _page(["stb-2021-1"], total=1)],
        calls,
    )

    client.search_amvbs()

    assert all(c["params"]["startRecord"] == "1" for c in calls)
    assert (
        calls[0]["params"]["query"]
        == "dt.type=AMvB sortBy dt.identifier/sort.ascending"
    )
    assert calls[1]["params"]["query"] == (
        'dt.type=AMvB AND dt.identifier>"stb-2020-099" sortBy dt.identifier/sort.ascending'
    )


def test_a_short_page_ends_the_search() -> None:
    calls: list[dict] = []
    client = _client(StaatsbladClient, [_page(["stb-2020-1", "stb-2020-2"])], calls)
    assert len(client.search_amvbs()) == 2
    assert len(calls) == 1


def test_pages_that_do_not_add_up_to_the_total_raise() -> None:
    client = _client(StaatsbladClient, [_page(["stb-2020-1"], total=250)], [])
    with pytest.raises(RuntimeError, match="hold 1 records, the service reports 250"):
        client.search_amvbs()
