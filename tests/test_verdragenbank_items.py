"""The item XML of a Verdragenbank treaty: its parties, Tractatenbladen, dossiers and
related treaties, from two real items (000004, 004630), retrieved and normalized."""

from __future__ import annotations

import pathlib
from typing import Any

import pytest
import requests

from lawgraph.clients.verdragenbank import VerdragenbankClient
from lawgraph.config.constants import (
    RAW_KIND_MISSING_SUFFIX,
    RAW_KIND_VERDRAG,
    RAW_KIND_VERDRAG_XML,
)
from lawgraph.core.models import Node, PipelineResult
from lawgraph.core.progress import Progress
from lawgraph.core.verdragenbank_xml import parse_treaty_xml, trb_official_id
from lawgraph.pipelines.normalize.verdragenbank import VerdragenbankNormalizePipeline
from lawgraph.pipelines.retrieve.verdragenbank import VerdragenbankRetrievePipeline
from tests.fakes import FakeResponse, RawSourcesFake

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
# Convention for the protection of the architectural heritage of Europe (Granada, 1985)
GRANADA = (FIXTURES / "verdragenbank_item_000004.xml").read_text()
# Protocol No. 2 to the ECHR (Strasbourg, 1963), a child of the ECHR (005132)
PROTOCOL_2 = (FIXTURES / "verdragenbank_item_004630.xml").read_text()


# ── the item XML ─────────────────────────────────────────────────────────────


def test_the_parties_with_their_dates_as_the_register_gives_them() -> None:
    treaty = parse_treaty_xml(GRANADA)

    assert treaty["place_signed"] == "Granada"
    assert len(treaty["parties"]) == 44
    assert treaty["parties"][0] == {
        "name": "Andorra",
        "signed": "1998-12-17",
        "ratified": "1999-07-28",
        "consent": "R",
        "provisional": None,
        "in_force": "1999-11-01",
        "retroactive": None,
        "denounced": None,
        "terminated": None,
        "reservation": False,
        "objection": False,
    }
    azerbaijan = next(p for p in treaty["parties"] if p["name"] == "Azerbeidzjan")
    assert azerbaijan["reservation"] is True


def test_the_tractatenbladen_with_their_official_id() -> None:
    treaty = parse_treaty_xml(GRANADA)

    assert treaty["tractatenblad"][:2] == [
        {
            "official_id": "trb-1985-163",
            "text": "1985, 163",
            "description": "En, Fr, vert. Ne",
        },
        {
            "official_id": "trb-1994-59",
            "text": "1994, 59",
            "description": "goedkeuring, inwerkingtreding",
        },
    ]


def test_the_kingdom_parts_and_the_dossiers_of_approval() -> None:
    treaty = parse_treaty_xml(GRANADA)

    assert treaty["kingdom_parts"][0] == {
        "part": "Nederland (in Europa)",
        "provisional": None,
        "in_force": "1994-06-01",
        "retroactive": None,
        "terminated": None,
    }
    assert treaty["kamerstukken"][:2] == [
        {"dossier": "22386", "rijks_number": None, "sub_number": None},
        {"dossier": "32047", "rijks_number": None, "sub_number": None},
    ]
    dossiers = [
        (k["dossier"], k["rijks_number"], k["sub_number"])
        for k in treaty["kamerstukken"]
    ]
    assert len(dossiers) == len(set(dossiers))


def test_a_protocol_names_the_convention_it_belongs_to() -> None:
    treaty = parse_treaty_xml(PROTOCOL_2)

    assert treaty["parent_treaties"] == [
        {
            "id": "005132",
            "title": "Verdrag tot bescherming van de rechten van de mens en de "
            "fundamentele vrijheden",
            "date": "1950-11-04",
            "place": "Rome",
        }
    ]
    assert treaty["child_treaties"] == []
    assert treaty["parties"] == []  # the register keeps none for a replaced Protocol
    assert treaty["kingdom_parts"][0]["terminated"] == "1998-11-01"
    assert (
        treaty["tractatenblad"][-1]["description"] == "vervanging door protocol nr. 11"
    )


@pytest.mark.parametrize(
    ("text", "official_id"),
    [
        ("1951, 154", "trb-1951-154"),
        (" 1964 ,  034 ", "trb-1964-34"),
        ("1951", None),
        (None, None),
    ],
)
def test_the_official_id_of_a_tractatenblad(
    text: str | None, official_id: str | None
) -> None:
    assert trb_official_id(text) == official_id


@pytest.mark.parametrize(
    "text", ["<html>Bad gateway", "<html><body>Onderhoud</body></html>"]
)
def test_what_is_no_treaty_is_refused(text: str) -> None:
    with pytest.raises(ValueError):
        parse_treaty_xml(text)


# ── the client ───────────────────────────────────────────────────────────────


def _client(answer: Any) -> VerdragenbankClient:
    client = VerdragenbankClient.__new__(VerdragenbankClient)

    def fake_get(url, *, timeout=30, **_kw):
        if isinstance(answer, Exception):
            raise answer
        return FakeResponse(answer)

    client._get_raw_absolute_with_retry = fake_get  # type: ignore[method-assign]
    return client


def _http_error(status: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(f"{status}", response=response)


def test_the_client_returns_the_item_xml_and_none_for_a_404() -> None:
    assert _client(GRANADA).fetch_treaty_xml("https://x/000004.xml") == GRANADA
    assert _client(_http_error(404)).fetch_treaty_xml("https://x/000009.xml") is None
    with pytest.raises(requests.HTTPError):
        _client(_http_error(503)).fetch_treaty_xml("https://x/000004.xml")


# ── the retrieve ─────────────────────────────────────────────────────────────


class _Client:
    def __init__(self, items: dict[str, Any]) -> None:
        self.items = items
        self.asked: list[str] = []

    def enumerate_treaties(
        self, max_records: int | None = None
    ) -> list[dict[str, Any]]:
        return [
            {
                "uri": f"https://repository.overheid.nl/frbr/vd/{identifier}",
                "verdragsnummer": identifier,
                "item_url": f"https://x/{identifier}.xml",
                "modified": "2026-09-01",
            }
            for identifier in self.items
        ]

    def fetch_treaty_xml(self, item_url: str) -> str | None:
        self.asked.append(item_url)
        answer = self.items[item_url.rsplit("/", 1)[-1].removesuffix(".xml")]
        if isinstance(answer, Exception):
            raise answer
        return answer


def _retrieve(
    items: dict[str, Any], unchanged: set[str] = frozenset()
) -> tuple[list, _Client]:
    client = _Client(items)
    pipeline = VerdragenbankRetrievePipeline(RawSourcesFake(), client=client)  # type: ignore[arg-type]
    pipeline._changed = lambda source, kind, listed: [  # type: ignore[method-assign]
        t["identifier"] for t in listed if t["identifier"] not in unchanged
    ]
    pipeline.progress = Progress("Verdragenbank")
    pipeline._without_missing = lambda source, kind, ids: list(ids)  # type: ignore[method-assign]
    return list(pipeline.fetch()), client


def test_the_retrieve_keeps_the_summary_and_the_item_xml_of_each_treaty() -> None:
    records, client = _retrieve(
        {"000004": GRANADA, "004630": PROTOCOL_2}, unchanged={"004630"}
    )

    summaries = [r for r in records if r.kind == RAW_KIND_VERDRAG]
    assert [r.external_id for r in summaries] == ["000004", "004630"]
    assert all("modified" not in r.payload_json for r in summaries)
    [item] = [r for r in records if r.kind == RAW_KIND_VERDRAG_XML]
    assert item.external_id == "000004"
    assert item.payload_text == GRANADA
    assert item.meta == {"item_url": "https://x/000004.xml", "modified": "2026-09-01"}
    assert client.asked == ["https://x/000004.xml"]  # 004630 did not change


def test_a_404_is_remembered_and_a_page_that_is_no_xml_is_not_kept() -> None:
    records, _ = _retrieve({"000009": None, "000026": "<html>Bad gateway"})

    items = [r for r in records if r.kind != RAW_KIND_VERDRAG]
    assert [(r.kind, r.external_id) for r in items] == [
        (RAW_KIND_VERDRAG_XML + RAW_KIND_MISSING_SUFFIX, "000009")
    ]


def test_only_stored_keeps_the_run_to_the_treaties_stored_already() -> None:
    client = _Client({"000004": GRANADA, "004630": PROTOCOL_2})
    pipeline = VerdragenbankRetrievePipeline(RawSourcesFake(), client=client)  # type: ignore[arg-type]
    pipeline.progress = Progress("Verdragenbank")
    pipeline._stored_at = lambda source, kind: {"004630": None}  # type: ignore[method-assign,assignment]
    pipeline._changed = lambda source, kind, listed: [t["identifier"] for t in listed]  # type: ignore[method-assign]
    pipeline._without_missing = lambda source, kind, ids: list(ids)  # type: ignore[method-assign]

    records = list(pipeline.fetch(only_stored=True))

    assert {r.external_id for r in records} == {"004630"}
    assert client.asked == ["https://x/004630.xml"]


# ── the normalize ────────────────────────────────────────────────────────────


class _Store(RawSourcesFake):
    def __init__(self) -> None:
        self.docs: list[dict[str, Any]] = []

    def bulk_insert_or_update_nodes(self, collection: str, docs: list[dict[str, Any]]):
        self.docs.extend(docs)
        return len(docs), 0

    def get_node(self, collection: str, key: str) -> Node | None:
        return None


def test_the_item_xml_is_merged_into_the_node_of_its_treaty() -> None:
    summary = {
        "external_id": "000004",
        "kind": RAW_KIND_VERDRAG,
        "payload_json": {
            "uri": "https://repository.overheid.nl/frbr/vd/000004",
            "verdragsnummer": "000004",
            "title_nl": "Verdrag tot bescherming van het architectonisch erfgoed van Europa",
            "treaty_type": "Multilateraal",
            "status": "Inwerkinggetreden",
        },
    }
    item = {
        "external_id": "000004",
        "kind": RAW_KIND_VERDRAG_XML,
        "payload_text": GRANADA,
    }
    store = _Store()

    count = VerdragenbankNormalizePipeline(store=store).normalize_nodes(
        [summary, item], PipelineResult()
    )

    assert count == 2
    [doc] = store.docs  # one batch, one node
    assert doc["props"]["title"].startswith(
        "Verdrag tot bescherming van het architectonisch"
    )
    assert doc["props"]["place_signed"] == "Granada"
    assert len(doc["props"]["parties"]) == 44
    assert doc["props"]["tractatenblad"][0]["official_id"] == "trb-1985-163"


def test_an_item_that_cannot_be_read_is_skipped() -> None:
    result = PipelineResult()
    item = {
        "external_id": "000026",
        "kind": RAW_KIND_VERDRAG_XML,
        "payload_text": "<html>",
    }

    count = VerdragenbankNormalizePipeline(store=_Store()).normalize_nodes(
        [item], result
    )

    assert count == 0
    assert result.skipped == 1


# ── the API ──────────────────────────────────────────────────────────────────


def test_the_detail_of_a_treaty_carries_its_register() -> None:
    from lawgraph.api.schemas.instruments import TreatyRegisterDTO

    register = TreatyRegisterDTO.from_props(parse_treaty_xml(PROTOCOL_2))

    assert register is not None
    assert register.place_signed == "Straatsburg"
    assert register.parent_treaties[0].id == "005132"
    assert register.tractatenblad[0].official_id == "trb-1963-123"
    assert TreatyRegisterDTO.from_props({"title": "Wet", "kind": "wet"}) is None


def test_the_register_page_of_the_reservations_only_when_a_party_made_one() -> None:
    from lawgraph.api.schemas.instruments import TreatyRegisterDTO

    granada = TreatyRegisterDTO.from_props(
        {**parse_treaty_xml(GRANADA), "treaty_number": "000004"}
    )
    protocol = TreatyRegisterDTO.from_props(
        {**parse_treaty_xml(PROTOCOL_2), "treaty_number": "004630"}
    )

    assert granada is not None and protocol is not None
    assert granada.reservations_url == (
        "https://verdragenbank.overheid.nl/nl/Verdrag/Details/000004_p.html#Voorbehouden"
    )
    assert protocol.reservations_url is None  # no parties, no reservations
