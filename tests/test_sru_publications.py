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

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
AMVB_PAGE = (FIXTURES / "sru_staatsblad_amvb_page.xml").read_text()  # 1 real record
UNKNOWN_INDEX = (FIXTURES / "sru_unknown_index_diagnostic.xml").read_text()


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
        return SimpleNamespace(text=response)

    client._get_raw_absolute_with_retry = fake_get
    return client


# ── searching ────────────────────────────────────────────────────────────────


def test_a_real_record_is_parsed_with_its_xml_url() -> None:
    records = _client(StaatsbladClient, [AMVB_PAGE], []).search_amvbs()
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
        }
    ]


def test_the_since_filter_uses_an_index_the_repository_knows() -> None:
    calls: list[dict] = []
    _client(StaatsbladClient, [AMVB_PAGE], calls).search_amvbs(since="2026-01-01")
    assert calls[0]["params"]["query"] == "dt.type=AMvB AND dt.modified>=2026-01-01"
    calls.clear()
    _client(StaatscourantClient, [AMVB_PAGE], calls).search_ministeriele_regelingen(
        since="2026-06-01"
    )
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
