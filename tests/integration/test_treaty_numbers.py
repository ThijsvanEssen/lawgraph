"""A treaty in the BWB and in the Verdragenbank is one treaty by its number, for real.

The BWB text of a treaty names its Verdragenbank id (``wetgeving@verdragnummer``), and the
Verdragenbank record is that id: ``normalize bwb`` and ``normalize verdragenbank`` write it
as ``treaty_number``, and the instrument detail names the other instrument of the number.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.commands.check import check
from lawgraph.config.constants import (
    RAW_KIND_BWB_TOESTAND,
    RAW_KIND_VERDRAG,
    SOURCE_BWB,
    SOURCE_VERDRAGENBANK,
)
from lawgraph.db import GraphStore, RawSourceWriter, raw_source_doc


def _toestand(bwb_id: str, number: str | None, title: str) -> str:
    attribute = f' verdragnummer="{number}"' if number else ""
    return (
        f'<toestand bwb-id="{bwb_id}" inwerkingtreding="1998-11-01">'
        f'<wetgeving soort="verdrag"{attribute}>'
        f"<intitule>{title}</intitule>"
        "<verdrag><artikel><kop><label>Artikel</label><nr>1</nr></kop>"
        "<al>De Hoge Verdragsluitende Partijen verzekeren een ieder.</al></artikel>"
        "</verdrag></wetgeving></toestand>"
    )


# BWB id, treaty number (None: the toestand names none), title
BWB_TREATIES = [
    ("BWBV0001000", "005132", "Verdrag tot bescherming van de rechten van de mens"),
    (
        "BWBV0002060",
        "000462",
        "Akkoord tussen de Nederlandse Minister van Sociale Zaken",
    ),
    ("BWBV0009999", None, "Een verdrag zonder nummer"),
]


def _verdrag(number: str, title: str) -> dict[str, Any]:
    return {
        "uri": f"https://verdragenbank.overheid.nl/nl/Verdrag/Details/{number}",
        "title": title,
        "title_nl": title,
        "title_en": None,
        "date_signed": "1950-11-04",
        "date_in_force": "1953-09-03",
        "treaty_type": "Multilateraal",
        "status": "Inwerkinggetreden",
        "verdragsnummer": number,
    }


@pytest.fixture()
def store(database: str, cli: Callable[..., Any]) -> Iterator[GraphStore]:
    store = GraphStore()
    with RawSourceWriter(store) as writer:
        for bwb_id, number, title in BWB_TREATIES:
            writer.add(
                raw_source_doc(
                    source=SOURCE_BWB,
                    kind=RAW_KIND_BWB_TOESTAND,
                    external_id=bwb_id,
                    payload_text=_toestand(bwb_id, number, title),
                    meta={"bwb_id": bwb_id, "state_url": f"https://repo/{bwb_id}.xml"},
                )
            )
        for number, title in (
            (
                "005132",
                "Verdrag tot bescherming van de rechten van de "
                "mens en de fundamentele vrijheden",
            ),
            ("001610", "Ander"),
        ):
            writer.add(
                raw_source_doc(
                    source=SOURCE_VERDRAGENBANK,
                    kind=RAW_KIND_VERDRAG,
                    external_id=number,
                    payload_json=_verdrag(number, title),
                )
            )
    cli("normalize", "bwb")
    cli("normalize", "verdragenbank")
    app.dependency_overrides[get_store] = lambda: store
    yield store
    app.dependency_overrides.pop(get_store, None)


def test_a_bwb_treaty_and_its_verdragenbank_record_name_each_other(
    store: GraphStore,
) -> None:
    client = TestClient(app)
    bwb = client.get("/api/instruments/BWBV0001000").json()
    assert bwb["treaty_number"] == "005132"
    assert [other["key"] for other in bwb["same_treaty"]] == ["verdrag_005132"]

    record = client.get("/api/instruments/verdrag_005132").json()
    assert record["treaty_number"] == "005132"
    assert [other["bwb_id"] for other in record["same_treaty"]] == ["BWBV0001000"]


def test_a_treaty_without_a_counterpart_has_none(store: GraphStore) -> None:
    client = TestClient(app)
    assert client.get("/api/instruments/BWBV0002060").json()["same_treaty"] == []
    assert client.get("/api/instruments/verdrag_001610").json()["same_treaty"] == []
    unnumbered = client.get("/api/instruments/BWBV0009999").json()
    assert unnumbered["treaty_number"] is None and unnumbered["same_treaty"] == []


def test_the_check_counts_what_the_numbers_match(store: GraphStore) -> None:
    notes = check(store, edges=False).notes
    assert (
        "treaties: 1 of 3 BWB treaties have a Verdragenbank record, 1 name a number it "
        "does not have, 1 name none"
    ) in notes
