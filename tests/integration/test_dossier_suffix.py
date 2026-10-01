"""A record on a budget chapter (37020-XV) belongs to that chapter, not to its number."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    RAW_KIND_EK_KAMERSTUK,
    RAW_KIND_TK_ACTIVITEIT,
    RAW_KIND_TK_DOCUMENT,
    RAW_KIND_TK_DOSSIER,
    RAW_KIND_TK_FRACTIE,
    RAW_KIND_TK_STEMMING,
    RAW_KIND_TK_ZAAK,
    SOURCE_EERSTEKAMER,
    SOURCE_TK,
)
from lawgraph.db import GraphStore, RawSourceWriter, raw_source_doc
from tests.integration.seed import uid

CHAPTER = {"Id": uid(2, 3), "Nummer": 37020, "Toevoeging": "XV"}
ZAAK = {
    "Id": uid(1, 2),
    "Nummer": "2026Z00001",
    "Soort": "Begroting",
    "Titel": "Vaststelling van de begrotingsstaat van het Ministerie van SZW (XV) 2027",
    "Kamerstukdossier": [CHAPTER],
}


def _records() -> list[tuple[str, dict[str, Any]]]:
    miljoenennota = {"Id": uid(1, 3), "Nummer": 37020, "Toevoeging": None}
    return [
        (RAW_KIND_TK_DOSSIER, {**miljoenennota, "Titel": "Miljoenennota 2027"}),
        (RAW_KIND_TK_DOSSIER, {**CHAPTER, "Titel": ZAAK["Titel"]}),
        # A sub-series of the EU council dossier, and a Koninkrijksrijkswet.
        (RAW_KIND_TK_DOSSIER, {"Id": uid(3, 3), "Nummer": 21501, "Toevoeging": "31"}),
        (
            RAW_KIND_TK_DOSSIER,
            {"Id": uid(4, 3), "Nummer": 36956, "Toevoeging": "(R2220)"},
        ),
        (RAW_KIND_TK_FRACTIE, {"Id": uid(1, 8), "Afkorting": "F1", "NaamNL": "F1"}),
        (RAW_KIND_TK_ZAAK, ZAAK),
        (
            RAW_KIND_TK_DOCUMENT,
            {
                "Id": uid(1, 1),
                "Soort": "Voorstel van wet",
                "Titel": ZAAK["Titel"],
                "Datum": "2026-09-15T00:00:00+02:00",
                "Volgnummer": 2,
                "Zaak": [ZAAK],
            },
        ),
        (
            RAW_KIND_TK_ACTIVITEIT,
            {
                "Id": uid(1, 11),
                "Nummer": "2026A00001",
                "Soort": "Wetgevingsoverleg",
                "Datum": "2026-11-02T00:00:00+01:00",
                "Agendapunt": [{"Zaak": [ZAAK]}],
            },
        ),
        (
            RAW_KIND_TK_STEMMING,
            {
                "Id": uid(1, 6),
                "Besluit_Id": uid(1, 7),
                "Soort": "Voor",
                "FractieGrootte": 10,
                "ActorFractie": "F1",
                "Fractie_Id": uid(1, 8),
                "Persoon_Id": None,
                "GewijzigdOp": "2026-11-10T10:00:00+01:00",
                "Besluit": {
                    "Id": uid(1, 7),
                    "BesluitSoort": "Stemmen - aangenomen",
                    "BesluitTekst": "Aangenomen.",
                    "StemmingsSoort": "Met handopsteken",
                    "Agendapunt": [{"Zaak": [ZAAK]}],
                },
            },
        ),
    ]


def _targets(store: GraphStore, collection: str, relation: str) -> list[str]:
    statement = """
    SELECT DISTINCT to_id FROM edges
    WHERE from_collection = %(collection)s AND relation = %(relation)s
      AND to_collection = 'dossiers'
    """
    rows = store.query(statement, {"collection": collection, "relation": relation})
    return sorted(rows)


def _props(store: GraphStore, key: str) -> dict[str, Any]:
    doc = store.get_document("dossiers", key)
    assert doc is not None
    return doc["props"]


def test_records_on_a_budget_chapter_link_to_the_chapter(
    database: str, cli: Any
) -> None:
    """The Zaak names Nummer 37020 with Toevoeging XV: the case, the bill, the debate
    and the vote belong to 37020-XV, and the Miljoenennota (37020) gets none of them."""
    store = GraphStore()
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

    cli("normalize", "tk")
    cli("normalize", "tk-dossiers")

    chapter = ["dossiers/37020_xv"]
    assert _targets(store, "cases", "PART_OF") == chapter
    assert _targets(store, "documents", "PART_OF") == chapter
    assert _targets(store, "activities", "ABOUT") == chapter
    assert _targets(store, "decisions", "ABOUT") == chapter

    budget, nota = _props(store, "37020_xv"), _props(store, "37020")
    assert budget["case_kinds"] == ["Begroting"]
    assert budget["kind"] == "Begroting"
    assert not nota.get("case_kinds")
    assert nota.get("kind") is None and nota.get("phases") is None

    # The API names the chapter by its label, and finds it by that label.
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        _senate_papers(store, cli)
        _api_names_the_chapter_by_its_label(client)
    finally:
        app.dependency_overrides.pop(get_store, None)


def _senate_papers(store: GraphStore, cli: Any) -> None:
    """Eerste Kamer papers name their dossier as ``37020 XV``: normalize gives them the
    label a Tweede Kamer paper has."""
    with RawSourceWriter(store) as writer:
        for number in ("37020 XV", "37021"):
            identifier = f"kst-{number.replace(' ', '-')}-A"
            writer.add(
                raw_source_doc(
                    source=SOURCE_EERSTEKAMER,
                    kind=RAW_KIND_EK_KAMERSTUK,
                    external_id=identifier,
                    payload_json={
                        "identifier": identifier,
                        "document_title": f"Begrotingsstaat {number}",
                        "dossier_number": number,
                    },
                )
            )
    cli("normalize", "eerstekamer")


def _get(client: TestClient, path: str, **params: Any) -> Any:
    response = client.get(path, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _api_names_the_chapter_by_its_label(client: TestClient) -> None:
    chapter = _get(client, "/api/dossiers/37020-XV")
    assert (chapter["key"], chapter["number"]) == ("37020_xv", "37020-XV")
    assert chapter["kind"] == "Begroting"
    nota = _get(client, "/api/dossiers/37020")
    assert (nota["key"], nota["number"]) == ("37020", "37020")
    # Every label the graph holds opens its dossier.
    for label, key in (("21501-31", "21501_31"), ("36956-(R2220)", "36956_r2220")):
        dossier = _get(client, f"/api/dossiers/{label}")
        assert (dossier["key"], dossier["number"]) == (key, label)

    # The paper of the chapter is in the chapter, not in the nota.
    (paper,) = _get(client, "/api/dossiers/37020-XV/documents")["items"]
    links = _get(client, f"/api/documents/{paper['key']}")
    assert links["dossier_numbers"] == ["37020-XV"]
    assert _get(client, "/api/dossiers/37020/documents")["total"] == 0

    assert _get(client, "/api/decisions", dossier="37020-XV")["total"] == 1
    assert _get(client, "/api/decisions", dossier="37020")["total"] == 0

    hits = _get(
        client, "/api/search", q="begrotingsstaat", types=["dossiers", "documents"]
    )["results"]
    assert [hit["extra"]["number"] for hit in hits["dossiers"]] == ["37020-XV"]
    assert sorted(hit["extra"]["dossier_number"] for hit in hits["documents"]) == [
        "37020-XV",
        "37020-XV",
        "37021",
    ]
