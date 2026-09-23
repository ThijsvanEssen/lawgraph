"""A record on a budget chapter (37020-XV) belongs to that chapter, not to its number."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    RAW_KIND_TK_ACTIVITEIT,
    RAW_KIND_TK_DOCUMENT,
    RAW_KIND_TK_DOSSIER,
    RAW_KIND_TK_FRACTIE,
    RAW_KIND_TK_STEMMING,
    RAW_KIND_TK_ZAAK,
    SOURCE_TK,
)
from lawgraph.db import ArangoStore, RawSourceWriter, raw_source_doc
from tests.integration.seed import uid, wait_for_views

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


def _targets(store: ArangoStore, collection: str, relation: str) -> list[str]:
    aql = """
    FOR e IN edges
        FILTER STARTS_WITH(e._from, @prefix) AND e.relation == @relation
        FILTER STARTS_WITH(e._to, "dossiers/")
        RETURN DISTINCT e._to
    """
    rows = store.query(aql, {"prefix": f"{collection}/", "relation": relation})
    return sorted(rows)


def test_records_on_a_budget_chapter_link_to_the_chapter(
    database: str, cli: Any
) -> None:
    """The Zaak names Nummer 37020 with Toevoeging XV: the case, the bill, the debate
    and the vote belong to 37020-XV, and the Miljoenennota (37020) gets none of them."""
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

    cli("normalize", "tk")
    cli("normalize", "tk-dossiers")

    chapter = ["dossiers/37020_xv"]
    assert _targets(store, "cases", "PART_OF") == chapter
    assert _targets(store, "documents", "PART_OF") == chapter
    assert _targets(store, "activities", "ABOUT") == chapter
    assert _targets(store, "decisions", "ABOUT") == chapter

    dossiers = store.db.collection("dossiers")
    budget, nota = dossiers.get("37020_xv")["props"], dossiers.get("37020")["props"]
    assert budget["case_kinds"] == ["Begroting"]
    assert budget["current_stage"] is not None
    assert not nota.get("case_kinds")
    assert nota["current_stage"] is None

    # The API names the chapter by its label, and finds it by that label.
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        _senate_papers(store)
        wait_for_views(store, {"search_dossiers": 2, "search_documents": 3})
        _api_names_the_chapter_by_its_label(client)
    finally:
        app.dependency_overrides.pop(get_store, None)


def _senate_papers(store: ArangoStore) -> None:
    """Eerste Kamer papers keep the number and the suffix of their dossier apart."""
    store.bulk_insert_or_update_nodes(
        "documents",
        [
            {
                "_key": f"ek_{number}_{suffix}",
                "type": "document",
                "labels": ["EersteKamer", "EK"],
                "props": {
                    "title": f"Begrotingsstaat {number} {suffix}",
                    "dossier_number": number,
                    **({"dossier_suffix": suffix} if suffix else {}),
                },
            }
            for number, suffix in (("37020", "XV"), ("37021", None))
        ],
    )


def _get(client: TestClient, path: str, **params: Any) -> Any:
    response = client.get(path, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _api_names_the_chapter_by_its_label(client: TestClient) -> None:
    chapter = _get(client, "/api/dossiers/37020-XV")
    assert (chapter["key"], chapter["number"]) == ("37020_xv", "37020-XV")
    assert chapter["current_stage"] is not None
    nota = _get(client, "/api/dossiers/37020")
    assert (nota["key"], nota["number"]) == ("37020", "37020")

    bulk = _get(client, "/api/dossiers/documents/bulk", numbers="37020,37020-XV,1")
    assert sorted(bulk["items"]) == ["37020", "37020-XV"]
    assert [len(bulk["items"][n]) for n in ("37020", "37020-XV")] == [0, 1]

    document = _get(client, "/api/documents", dossier="37020-XV")["items"]
    assert len(document) == 1
    links = _get(client, f"/api/documents/{document[0]['key']}")
    assert links["dossier_numbers"] == ["37020-XV"]
    assert _get(client, "/api/documents", dossier="37020")["total"] == 0

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
