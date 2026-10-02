"""The agendas of the Eerste Kamer as activities, on a real database: a block of a plenary
sitting and a committee meeting, about the dossiers they name and led by the committees a
meeting names, on the dossier's timeline with the page they were taken from."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    RAW_KIND_EK_COMMITTEE_DAY,
    RAW_KIND_EK_PLENARY,
    SOURCE_EERSTEKAMER,
)
from lawgraph.core.models import Node, NodeType
from lawgraph.db import GraphStore, NodeWriter, RawSourceWriter, raw_source_doc

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SITE = "https://www.eerstekamer.nl"


def _node(collection: str, node_type: NodeType, key: str, **props: Any) -> Node:
    return Node(
        collection=collection, type=node_type, key=key, labels=["EK"], props=props
    )


def test_the_agendas_become_activities_about_their_dossiers(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    with NodeWriter(store) as writer:
        writer.add_all(
            [
                _node(
                    "dossiers", NodeType.DOSSIER, "36937", number="36937", label="36937"
                ),
                _node(
                    "dossiers", NodeType.DOSSIER, "28973", number="28973", label="28973"
                ),
                _node(
                    "committees",
                    NodeType.COMMITTEE,
                    "ek_lnv",
                    name="Landbouw, Natuur en Voedselkwaliteit",
                    abbreviation="LNV",
                    chamber="EK",
                    slug="ek-lnv",
                ),
            ]
        )
    with RawSourceWriter(store) as writer:
        for kind, external_id, name, path in (
            (
                RAW_KIND_EK_PLENARY,
                "/plenaire_vergadering/20261006",
                "ek_plenary_20261006.html",
                "/plenaire_vergadering/20261006",
            ),
            (
                RAW_KIND_EK_COMMITTEE_DAY,
                "2026-09-29",
                "ek_committee_day_20260929.html",
                "/commissievergaderingen_op?key=vn1bx0000000",
            ),
        ):
            writer.add(
                raw_source_doc(
                    source=SOURCE_EERSTEKAMER,
                    kind=kind,
                    external_id=external_id,
                    payload_text=(FIXTURES / name).read_text(),
                    meta={"url": SITE + path, "read_on": "2026-10-03"},
                )
            )
    cli("normalize", "eerstekamer-agenda")

    hammer = store.get_document("activities", "ek_vn1cminyu18p")["props"]
    assert (hammer["chamber"], hammer["date"], hammer["time"]) == (
        "EK",
        "2026-10-06",
        "13.30-13.35",
    )
    assert hammer.get("status") is None  # the Eerste Kamer gives none
    meeting = store.get_document("activities", "ek_20260929_lnv_en_vws")["props"]
    assert meeting["source_url"] == SITE + "/commissievergadering/20260929_lnv_en_vws"
    assert meeting["decision_points"][0]["dossiers"] == ["28973", "29683", "32793"]
    led = list(
        store.query(
            "SELECT from_id, to_id FROM edges WHERE relation = 'LED_BY'"
            " ORDER BY from_id ASC NULLS FIRST"
        )
    )
    assert led == [
        {"from_id": "activities/ek_20260929_lnv_en_vws", "to_id": "committees/ek_lnv"}
    ]

    app.dependency_overrides[get_store] = lambda: store
    try:
        timeline = TestClient(app).get("/api/dossiers/36937/timeline").json()
    finally:
        app.dependency_overrides.pop(get_store, None)
    (entry,) = [e for e in timeline["entries"] if e["node_type"] == "activity"]
    assert entry["body"]["chamber"] == "EK"
    assert entry["body"]["agenda_title"] == "Hamerstukken"
    assert entry["body"]["source_url"] == SITE + "/plenaire_vergadering/20261006"
    assert entry["body"]["retrieved_on"] == "2026-10-03"
    assert entry["planned"] is False
