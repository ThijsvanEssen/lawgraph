"""The item XML of a Verdragenbank treaty: its parties, Tractatenbladen, dossiers and
related treaties, from two real items (000004, 004630), retrieved and normalized."""

from __future__ import annotations

import datetime as dt
from collections.abc import Collection
from typing import Any, cast

import pytest
import requests

from lawgraph.clients.base import ATTEMPTS, UnexpectedAnswer
from lawgraph.clients.verdragenbank import VerdragenbankClient
from lawgraph.config.constants import (
    RAW_KIND_MISSING_SUFFIX,
    RAW_KIND_VERDRAGENBANK_JSON,
    RAW_KIND_VERDRAGENBANK_XML,
)
from lawgraph.core.models import PipelineResult
from lawgraph.core.progress import Progress
from lawgraph.core.verdragenbank_xml import parse_treaty_xml, trb_official_id
from lawgraph.pipelines.normalize.verdragenbank import VerdragenbankNormalizePipeline
from lawgraph.pipelines.retrieve.verdragenbank import VerdragenbankRetrievePipeline
from tests.fakes import InMemoryStore, ScriptedSession, http_error
from tests.paths import fixture_text

# Convention for the protection of the architectural heritage of Europe (Granada, 1985)
GRANADA = fixture_text("verdragenbank_item_000004.xml")
# Protocol No. 2 to the ECHR (Strasbourg, 1963), a child of the ECHR (005132)
PROTOCOL_2 = fixture_text("verdragenbank_item_004630.xml")


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


def _client(*answers: Any) -> VerdragenbankClient:
    return VerdragenbankClient(session=ScriptedSession(*answers))


def test_the_client_returns_the_item_xml_and_raises_for_what_is_not(slept) -> None:
    assert _client(GRANADA).fetch_treaty_xml("https://x/000004.xml") == GRANADA
    for status in (404, 503):
        with pytest.raises(requests.HTTPError):
            failed = [http_error(status)] * ATTEMPTS
            _client(*failed).fetch_treaty_xml("https://x/000004.xml")
    with pytest.raises(UnexpectedAnswer):
        _client("<html>Bad gateway").fetch_treaty_xml("https://x/000026.xml")


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

    def fetch_treaty_xml(self, item_url: str) -> str:
        self.asked.append(item_url)
        answer = self.items[item_url.rsplit("/", 1)[-1].removesuffix(".xml")]
        if isinstance(answer, Exception):
            raise answer
        return answer


def _retrieve(
    items: dict[str, Any], unchanged: Collection[str] = frozenset()
) -> tuple[list, _Client]:
    client = _Client(items)
    pipeline = VerdragenbankRetrievePipeline(
        InMemoryStore(), client=cast(VerdragenbankClient, client)
    )
    pipeline._changed = lambda source, kind, listed: [
        t["identifier"] for t in listed if t["identifier"] not in unchanged
    ]
    pipeline.progress = Progress("Verdragenbank")
    pipeline._without_missing = lambda source, kind, ids: list(ids)
    return list(pipeline.fetch()), client


def test_the_retrieve_keeps_the_summary_and_the_item_xml_of_each_treaty() -> None:
    records, client = _retrieve(
        {"000004": GRANADA, "004630": PROTOCOL_2}, unchanged={"004630"}
    )

    summaries = [r for r in records if r.kind == RAW_KIND_VERDRAGENBANK_JSON]
    assert [r.external_id for r in summaries] == ["000004", "004630"]
    assert all("modified" not in r.payload_json for r in summaries)
    [item] = [r for r in records if r.kind == RAW_KIND_VERDRAGENBANK_XML]
    assert item.external_id == "000004"
    assert item.payload_text == GRANADA
    assert item.meta == {"item_url": "https://x/000004.xml", "modified": "2026-09-01"}
    assert client.asked == ["https://x/000004.xml"]  # 004630 did not change


def test_a_404_is_remembered_and_a_page_that_is_no_xml_is_not_kept() -> None:
    records, _ = _retrieve(
        {"000009": http_error(404), "000026": UnexpectedAnswer("not XML")}
    )

    items = [r for r in records if r.kind != RAW_KIND_VERDRAGENBANK_JSON]
    assert [(r.kind, r.external_id) for r in items] == [
        (RAW_KIND_VERDRAGENBANK_XML + RAW_KIND_MISSING_SUFFIX, "000009")
    ]


def test_only_stored_keeps_the_run_to_the_treaties_stored_already() -> None:
    client = _Client({"000004": GRANADA, "004630": PROTOCOL_2})
    pipeline = VerdragenbankRetrievePipeline(
        InMemoryStore(), client=cast(VerdragenbankClient, client)
    )
    pipeline.progress = Progress("Verdragenbank")
    pipeline._stored_at = lambda source, kind: {"004630": dt.datetime(2026, 1, 1)}
    pipeline._changed = lambda source, kind, listed: [t["identifier"] for t in listed]
    pipeline._without_missing = lambda source, kind, ids: list(ids)

    records = list(pipeline.fetch(only_stored=True))

    assert {r.external_id for r in records} == {"004630"}
    assert client.asked == ["https://x/004630.xml"]


# ── the normalize ────────────────────────────────────────────────────────────


def _written(store: InMemoryStore) -> list[dict[str, Any]]:
    """The node documents *store* is given from now on, write by write."""
    written: list[dict[str, Any]] = []
    write = store.bulk_insert_or_update_nodes

    def spy(collection: str, docs: list[dict[str, Any]]) -> tuple[int, int]:
        written.extend(docs)
        return write(collection, docs)

    store.bulk_insert_or_update_nodes = spy
    return written


def test_the_item_xml_is_merged_into_the_node_of_its_treaty() -> None:
    summary = {
        "external_id": "000004",
        "kind": RAW_KIND_VERDRAGENBANK_JSON,
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
        "kind": RAW_KIND_VERDRAGENBANK_XML,
        "payload_text": GRANADA,
    }
    store = InMemoryStore()
    written = _written(store)

    VerdragenbankNormalizePipeline(store=store).write([summary, item], PipelineResult())

    [doc] = written  # one batch, one node
    assert doc["props"]["title"].startswith(
        "Verdrag tot bescherming van het architectonisch"
    )
    assert doc["props"]["place_signed"] == "Granada"
    assert len(doc["props"]["parties"]) == 44
    assert doc["props"]["tractatenblad"][0]["official_id"] == "trb-1985-163"


def test_an_item_that_cannot_be_read_fails_and_names_the_treaty() -> None:
    result = PipelineResult()
    item = {
        "external_id": "000026",
        "kind": RAW_KIND_VERDRAGENBANK_XML,
        "payload_text": "<html>",
    }
    pipeline = VerdragenbankNormalizePipeline(store=InMemoryStore())

    pipeline.write([item], result)
    pipeline.add_outcomes(result)

    assert pipeline.store.writes.created == 0
    assert result.skipped == 1
    (error,) = result.errors
    assert "000026" in error


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
