"""A signature says in which capacity it was made: a person's role changes over time."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    RAW_KIND_TK_DOCUMENT,
    RAW_KIND_TK_DOSSIER,
    RAW_KIND_TK_FRACTIE,
    RAW_KIND_TK_PERSOON,
    SOURCE_TK,
)
from lawgraph.core.models import make_node_key
from lawgraph.db import ArangoStore, RawSourceWriter, raw_source_doc
from tests.integration.seed import uid

JETTEN = uid(1, 9)
BUMA = uid(2, 9)
D66 = uid(1, 8)
DOSSIER = {"Id": uid(1, 3), "Nummer": 36999, "Toevoeging": None, "Titel": "Onderwijs"}
ZAAK = {"Id": uid(1, 2), "Soort": "Wetgeving", "Kamerstukdossier": [DOSSIER]}


def _document(number: int, kind: str, date: str, actor: dict[str, Any]) -> dict:
    return {
        "Id": uid(number, 1),
        "DocumentNummer": f"2026D0000{number}",
        "Soort": kind,
        "Titel": kind,
        "Datum": f"{date}T00:00:00+02:00",
        "Zaak": [ZAAK],
        "DocumentActor": [{"Relatie": "Eerste ondertekenaar", **actor}],
    }


def _records() -> list[tuple[str, dict[str, Any]]]:
    return [
        (RAW_KIND_TK_DOSSIER, DOSSIER),
        (RAW_KIND_TK_FRACTIE, {"Id": D66, "Afkorting": "D66", "NaamNL": "D66"}),
        (
            RAW_KIND_TK_PERSOON,
            {"Id": JETTEN, "Voornamen": "Rob", "Achternaam": "Jetten"},
        ),
        (
            RAW_KIND_TK_PERSOON,
            {"Id": BUMA, "Voornamen": "Sybrand", "Achternaam": "Buma"},
        ),
        (
            RAW_KIND_TK_DOCUMENT,
            _document(
                1,
                "Motie",
                "2025-06-01",
                {
                    "Persoon_Id": JETTEN,
                    "ActorNaam": "R.A.A. Jetten",
                    "ActorFractie": "D66",
                    "Fractie_Id": D66,
                    "Functie": "Tweede Kamerlid",
                },
            ),
        ),
        (
            RAW_KIND_TK_DOCUMENT,
            _document(
                2,
                "Brief regering",
                "2026-03-01",
                {
                    "Persoon_Id": JETTEN,
                    "ActorNaam": "R.A.A. Jetten",
                    "Functie": "minister-president",
                },
            ),
        ),
        (
            RAW_KIND_TK_DOCUMENT,
            _document(
                3,
                "Advies Afdeling advisering Raad van State",
                "2026-04-01",
                {
                    "Persoon_Id": BUMA,
                    "ActorNaam": "S. van Haersma Buma",
                    "Functie": "vicepresident van de Raad van State",
                },
            ),
        ),
    ]


def test_each_signature_carries_the_function_and_capacity_of_its_day(
    database: str, cli: Any
) -> None:
    store = ArangoStore()
    with RawSourceWriter(store) as writer:
        for kind, payload in _records():
            writer.add(
                raw_source_doc(
                    source=SOURCE_TK,
                    kind=kind,
                    external_id=payload["Id"],
                    payload_json=payload,
                )
            )
    cli("normalize", "tk-dossiers")

    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        jetten, buma = make_node_key(JETTEN), make_node_key(BUMA)

        signed = _authored(client, jetten)
        assert signed == {
            "Motie": ("Tweede Kamerlid", "kamerlid"),
            "Brief regering": ("minister-president", "bewindspersoon"),
        }
        assert _authored(client, buma) == {
            "Advies Afdeling advisering Raad van State": (
                "vicepresident van de Raad van State",
                "overig",
            )
        }

        dossiers = client.get(f"/api/members/{jetten}/dossiers").json()["items"]
        assert [(d["number"], d["capacities"], d["functions"]) for d in dossiers] == [
            (
                "36999",
                ["bewindspersoon", "kamerlid"],
                ["minister-president", "Tweede Kamerlid"],  # the server's collation
            )
        ]
    finally:
        app.dependency_overrides.pop(get_store, None)


def _authored(client: TestClient, member_key: str) -> dict[str, tuple[str, str]]:
    """Kind of document -> (function, capacity) of the member's AUTHORED edges."""
    node = client.get(f"/api/nodes/members/{member_key}").json()
    return {
        item["props"]["kind"]: (item["meta"]["function"], item["meta"]["capacity"])
        for bucket in node["neighbors"]["buckets"]
        if bucket["relation"] == "AUTHORED"
        for item in bucket["items"]
    }
