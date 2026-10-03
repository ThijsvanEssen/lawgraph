"""A toezegging has its own number, how the Kamer cites it (J28): the real ``normalize
tk-dossiers`` keeps ``Nummer``, the list shows it and ``/api/resolve`` finds it."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import RAW_KIND_TK_TOEZEGGING, SOURCE_TK
from lawgraph.db import GraphStore, RawSourceWriter, raw_source_doc
from tests.integration.seed import uid

COMMITMENT = {
    "Id": uid(1, 5),
    "Nummer": "TZ202603-130",
    "Aanmaakdatum": "2026-03-19T17:42:13.69+01:00",
    "ActiviteitNummer": "2026A01894",
    "Naam": "Herbert, H.G.",
    "Functie": "Minister van Economische Zaken en Klimaat",
    "Status": "Openstaand",
    "DatumNakoming": "0001-01-01T00:00:00Z",
    "Tekst": "De minister zegt toe de Kamer voor de zomer te informeren.",
    "Verwijderd": False,
}


def test_a_commitment_is_listed_and_found_by_its_number(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    with RawSourceWriter(store) as writer:
        writer.add(
            raw_source_doc(
                source=SOURCE_TK,
                kind=RAW_KIND_TK_TOEZEGGING,
                external_id=COMMITMENT["Id"],
                payload_json=COMMITMENT,
            )
        )
    cli("normalize", "tk-dossiers")
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        listed = client.get("/api/commitments", params={"limit": 1}).json()
        resolved = client.get("/api/resolve", params={"q": "tz202603-130"}).json()
    finally:
        app.dependency_overrides.pop(get_store, None)

    (item,) = listed["items"]
    assert (item["number"], item["expected_resolution"]) == ("TZ202603-130", None)
    assert (resolved["kind"], resolved["match"]["key"]) == ("commitment", item["key"])
