"""A toezegging has its own number, how the Kamer cites it (J28): the real ``normalize
tk-dossiers`` keeps ``Nummer``, the list shows it and ``/api/resolve`` finds it."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import RAW_KIND_TK_TOEZEGGING
from lawgraph.db import GraphStore
from tests.integration.seed import uid, write_tk

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
    write_tk(store, [(RAW_KIND_TK_TOEZEGGING, COMMITMENT)])
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


def test_the_newest_registered_first_and_an_impossible_due_day_a_gap(
    database: str, cli: Any
) -> None:
    """The Kamer registers a commitment weeks after its debate: ``sort=registered_on`` puts
    it first, and ``/api/stats`` gives the day for the freshness watch. A ``DatumNakoming``
    no commitment can be due (``0025-01-28`` in the source) is a gap, not corrected."""
    later = {
        **COMMITMENT,
        "Id": uid(1, 6),
        "Nummer": "TZ202610-228",
        "Aanmaakdatum": "2026-10-28T11:29:00+01:00",
        "DatumNakoming": "0025-01-28T00:00:00Z",
        "Activiteit": [{"Id": uid(1, 7), "Datum": "2026-02-15T10:00:00+01:00"}],
    }
    store = GraphStore()
    write_tk(
        store, [(RAW_KIND_TK_TOEZEGGING, COMMITMENT), (RAW_KIND_TK_TOEZEGGING, later)]
    )
    cli("normalize", "tk-dossiers")
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        by_date = client.get("/api/commitments").json()
        registered = client.get("/api/commitments?sort=registered_on").json()
        tk = client.get("/api/stats").json()["data_as_of"]["tk"]
    finally:
        app.dependency_overrides.pop(get_store, None)

    assert [i["number"] for i in by_date["items"]] == ["TZ202603-130", "TZ202610-228"]
    assert [
        (i["number"], i["expected_resolution"], i["expected_resolution_impossible"])
        for i in registered["items"]
    ] == [("TZ202610-228", None, "0025-01-28"), ("TZ202603-130", None, None)]
    assert tk["commitments_registered"] == "2026-10-28"
