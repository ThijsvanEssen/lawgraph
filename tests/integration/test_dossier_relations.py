"""From Prinsjesdag to everything around it: the dossiers of one number, the budget a change
revises, the nota it accompanies and the dossiers of the cases the Kamer relates; and the
pages on tweedekamer.nl, derived from the numbers the site knows."""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    RAW_KIND_TK_ACTIVITEIT,
    RAW_KIND_TK_DOCUMENT,
    RAW_KIND_TK_DOSSIER,
    RAW_KIND_TK_ZAAK,
    SOURCE_TK,
)
from lawgraph.db import ArangoStore, RawSourceWriter, raw_source_doc
from tests.integration.seed import uid

_MILJOENENNOTA = "Nota over de toestand van ’s Rijks Financiën"
_CHANGE = (
    "Wijziging van de begrotingsstaten van het Ministerie van {name} ({chapter}) voor het "
    "jaar 2026 (wijziging samenhangende met de Miljoenennota)"
)
_BUDGET = (
    "Vaststelling van de begrotingsstaten van het Ministerie van {name} ({chapter}) voor "
    "het jaar {year}"
)
_VRO = "Volkshuisvesting en Ruimtelijke Ordening"

# Nummer, Toevoeging, Titel; in no particular order.
_DOSSIERS = [
    (37035, "XXII", _CHANGE.format(name=_VRO, chapter="XXII")),
    (37035, "III", _CHANGE.format(name="Algemene Zaken", chapter="IIIA")),
    (37035, "IIA", _CHANGE.format(name="de Staten-Generaal", chapter="IIA")),
    (36800, None, _MILJOENENNOTA),
    (36800, "XXII", _BUDGET.format(name=_VRO, chapter="XXII", year=2026)),
    (36800, "III", _BUDGET.format(name="Algemene Zaken", chapter="IIIA", year=2026)),
    (37020, None, _MILJOENENNOTA),
    (37020, "XXII", _BUDGET.format(name=_VRO, chapter="XXII", year=2027)),
    (21501, "02", "Raad Algemene Zaken en Raad Buitenlandse Zaken"),
]


def _records(today: dt.date) -> list[tuple[str, dict[str, Any]]]:
    records: list[tuple[str, dict[str, Any]]] = [
        (
            RAW_KIND_TK_DOSSIER,
            {"Id": uid(i + 1, 3), "Nummer": n, "Toevoeging": s, "Titel": t},
        )
        for i, (n, s, t) in enumerate(_DOSSIERS)
    ]
    change = {
        "Id": uid(1, 2),
        "Nummer": "2026Z17098",
        "Soort": "Begroting",
        "Kamerstukdossier": [{"Nummer": 37035, "Toevoeging": "XXII"}],
    }
    # A letter in the EU Council series answers a motion on the 2026 budget; the motion's
    # own case was not retrieved, its dossier comes with the relation.
    letter = {
        "Id": uid(2, 2),
        "Nummer": "2026Z10000",
        "Soort": "Brief regering",
        "Kamerstukdossier": [{"Nummer": 21501, "Toevoeging": "02"}],
        "GerelateerdNaar": [
            {
                "Id": uid(3, 2),
                "Soort": "Motie",
                "Verwijderd": False,
                "Kamerstukdossier": [{"Nummer": 36800, "Toevoeging": "XXII"}],
            }
        ],
    }
    records += [(RAW_KIND_TK_ZAAK, change), (RAW_KIND_TK_ZAAK, letter)]
    records.append(
        (
            RAW_KIND_TK_DOCUMENT,
            {
                "Id": "a0ec76e1-44ff-49d3-924b-2a4a8af4698c",
                "DocumentNummer": "2026D44984",
                "Soort": "Voorstel van wet",
                "Titel": _DOSSIERS[0][2],
                "Datum": f"{today.isoformat()}T00:00:00+02:00",
                "Volgnummer": 2,
                "Zaak": [change],
            },
        )
    )
    records.append(
        (
            RAW_KIND_TK_ACTIVITEIT,
            {
                "Id": "72da4199-b2ec-4f4e-9a19-53071d8e1ab4",
                "Nummer": "2026A02881",
                "Soort": "Plenair debat (wetgeving)",
                "Datum": f"{today.isoformat()}T00:00:00+02:00",
                "Agendapunt": [{"Zaak": [change]}],
            },
        )
    )
    return records


def _relation_edges(store: ArangoStore) -> list[tuple[str, str, str, Any]]:
    aql = """
    FOR e IN edges
        FILTER e.source == "tk-dossier-relations"
        SORT e._key
        RETURN [e.relation, e._from, e._to, e.meta]
    """
    return [tuple(row) for row in store.query(aql)]


def test_the_dossiers_around_prinsjesdag_are_related_and_linked(
    database: str, cli: Any
) -> None:
    store = ArangoStore()
    today = dt.date.today()
    with RawSourceWriter(store) as writer:
        for kind, payload in _records(today):
            writer.add(
                raw_source_doc(
                    source=SOURCE_TK,
                    kind=kind,
                    external_id=payload["Id"],
                    payload_json=payload,
                )
            )

    cli("normalize", "tk")
    cli("normalize", "tk-dossiers")
    cli("semantic", "tk-dossier-relations")

    edges = _relation_edges(store)
    assert {(r, f, t) for r, f, t, _ in edges} == {
        ("REVISES", "dossiers/37035_xxii", "dossiers/36800_xxii"),
        ("REVISES", "dossiers/37035_iii", "dossiers/36800_iii"),
        ("ACCOMPANIES", "dossiers/37035_xxii", "dossiers/37020"),
        ("ACCOMPANIES", "dossiers/37035_iii", "dossiers/37020"),
        ("ACCOMPANIES", "dossiers/37035_iia", "dossiers/37020"),
        ("RELATED_TO", "dossiers/21501_02", "dossiers/36800_xxii"),
    }
    # 37035-IIA has no budget of 2026 in the graph: it revises nothing.
    cli("semantic", "tk-dossier-relations")
    assert _relation_edges(store) == edges  # the same keys and meta, nothing added

    dossiers = store.db.collection("dossiers")
    assert dossiers.get("37035_xxii")["props"]["same_number_count"] == 2
    assert dossiers.get("21501_02")["props"]["same_number_count"] == 0

    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        _the_api_lists_the_dossiers_of_a_number(client)
        _the_api_shows_the_relations_with_their_direction(client)
        _the_lists_find_a_number(client)
        _the_pages_on_tweedekamer_nl_follow_from_the_numbers(client)
    finally:
        app.dependency_overrides.pop(get_store, None)


def _get(client: TestClient, path: str, **params: Any) -> Any:
    response = client.get(path, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _the_api_lists_the_dossiers_of_a_number(client: TestClient) -> None:
    budget = _get(client, "/api/dossiers", number="36800")
    assert [d["number"] for d in budget["items"]] == [
        "36800",
        "36800-III",
        "36800-XXII",
    ]
    assert budget["total"] == 3
    assert [(d["suffix"], d["same_number_count"]) for d in budget["items"]] == [
        (None, 2),
        ("III", 2),
        ("XXII", 2),
    ]
    change = _get(client, "/api/dossiers", number="37035")["items"]
    assert [d["number"] for d in change] == ["37035-IIA", "37035-III", "37035-XXII"]
    unknown = _get(client, "/api/dossiers", number="99999")
    assert (unknown["total"], unknown["items"]) == (0, [])
    # a prefix: the chapters of a number, or one chapter
    chapters = _get(client, "/api/dossiers", number="37035-")["items"]
    assert [d["number"] for d in chapters] == ["37035-IIA", "37035-III", "37035-XXII"]
    one = _get(client, "/api/dossiers", number="37035-XXII")["items"]
    assert [d["number"] for d in one] == ["37035-XXII"]
    assert client.get("/api/dossiers", params={"number": "x"}).status_code == 422


def _relations(dossier: dict[str, Any]) -> list[tuple[str, str, str]]:
    return [
        (r["relation"], r["direction"], r["dossier"]["number"])
        for r in dossier["relations"]
    ]


def _the_api_shows_the_relations_with_their_direction(client: TestClient) -> None:
    change = _get(client, "/api/dossiers/37035-XXII")
    assert _relations(change) == [
        ("revises", "outgoing", "36800-XXII"),
        ("accompanies", "outgoing", "37020"),
    ]
    assert change["relations"][0]["rule"] == "begrotingswijziging"
    assert change["relations"][1]["nota"] == "miljoenennota"
    assert change["track"] == "begroting" and change["same_number_count"] == 2

    budget = _get(client, "/api/dossiers/36800-XXII")
    assert _relations(budget) == [
        ("revises", "incoming", "37035-XXII"),
        ("related_to", "incoming", "21501-02"),
    ]
    related = budget["relations"][1]
    assert (related["cases"], related["case_kinds"]) == (1, ["Brief regering → Motie"])

    nota = _get(client, "/api/dossiers/37020")
    assert nota["track"] == "nota"
    assert [(r, d) for r, d, _ in _relations(nota)] == [("accompanies", "incoming")] * 3

    # The node response has the same edges, with their direction.
    assert _buckets(_get(client, "/api/nodes/dossiers/37035_xxii")) >= {
        ("REVISES", "outbound"),
        ("ACCOMPANIES", "outbound"),
    }
    assert _buckets(_get(client, "/api/nodes/dossiers/36800_xxii")) >= {
        ("REVISES", "inbound"),
        ("RELATED_TO", "inbound"),
    }


def _buckets(node: dict[str, Any]) -> set[tuple[str, str]]:
    return {(b["relation"], b["direction"]) for b in node["neighbors"]["buckets"]}


def _the_lists_find_a_number(client: TestClient) -> None:
    listed = _get(client, "/api/dossiers/open", subject="37035")
    assert sorted(d["number"] for d in listed["items"]) == [
        "37035-IIA",
        "37035-III",
        "37035-XXII",
    ]
    one = _get(client, "/api/dossiers/open", subject="37035-xxii")["items"]
    assert [d["number"] for d in one] == ["37035-XXII"]
    words = _get(client, "/api/dossiers/open", subject="Raad Algemene")["items"]
    assert [d["number"] for d in words] == ["21501-02"]
    recent = _get(client, "/api/dossiers/recent", subject="37035")
    assert [d["number"] for d in recent] == ["37035-XXII"]
    assert _get(client, "/api/dossiers/recent", subject="36800") == []


def _the_pages_on_tweedekamer_nl_follow_from_the_numbers(client: TestClient) -> None:
    timeline = _get(client, "/api/dossiers/37035-XXII/timeline")["entries"]
    links = {entry["node_type"]: entry["tk_url"] for entry in timeline}
    assert links == {
        "document": "https://www.tweedekamer.nl/kamerstukken/detail"
        "?id=2026D44984&did=2026D44984",
        "activity": "https://www.tweedekamer.nl/debat_en_vergadering/"
        "plenaire_vergaderingen/details/activiteit?id=2026A02881",
    }
    documents = _get(client, "/api/dossiers/37035-XXII/documents")["items"]
    assert documents[0]["tk_url"] == links["document"]
    detail = _get(client, f"/api/documents/{documents[0]['key']}")
    assert detail["tk_url"] == links["document"]
    assert detail["file_url"].endswith(
        "/Document(a0ec76e1-44ff-49d3-924b-2a4a8af4698c)/resource"
    )
    node = _get(client, f"/api/nodes/documents/{documents[0]['key']}")
    assert node["node"]["props"]["tk_url"] == links["document"]
