"""A decision says which dossiers it was taken in and in which chamber."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    RAW_KIND_TK_DOSSIER,
    RAW_KIND_TK_FRACTIE,
    RAW_KIND_TK_STEMMING,
    SOURCE_TK,
)
from lawgraph.core.models import make_node_key
from lawgraph.db import ArangoStore, RawSourceWriter, raw_source_doc
from tests.integration.seed import uid

DOSSIER = {"Id": uid(1, 3), "Nummer": 36774, "Toevoeging": None, "Titel": "Wet ACM"}
ZAAK = {
    "Id": uid(1, 2),
    "Nummer": "2025Z13247",
    "Soort": "Initiatiefwetgeving",
    "Titel": "Wet inroepbevoegdheid ACM",
    "Kamerstukdossier": [DOSSIER],
}
DECISION_ID = uid(1, 7)
VOTE = {
    "Id": uid(1, 6),
    "Besluit_Id": DECISION_ID,
    "Soort": "Voor",
    "FractieGrootte": 10,
    "ActorFractie": "F1",
    "Fractie_Id": uid(1, 8),
    "Persoon_Id": None,
    "GewijzigdOp": "2026-09-22T10:00:00+02:00",
    "Besluit": {
        "Id": DECISION_ID,
        "BesluitSoort": "Stemmen - aangenomen",
        "BesluitTekst": "Aangenomen.",
        "StemmingsSoort": "Met handopsteken",
        "Zaak": [ZAAK],
        "Agendapunt": [{"Zaak": [ZAAK]}],
    },
}


def test_a_decision_names_its_dossiers_and_its_chamber(database: str, cli: Any) -> None:
    store = ArangoStore()
    with RawSourceWriter(store) as writer:
        for kind, payload in (
            (RAW_KIND_TK_DOSSIER, DOSSIER),
            (RAW_KIND_TK_FRACTIE, {"Id": uid(1, 8), "Afkorting": "F1", "NaamNL": "F1"}),
            (RAW_KIND_TK_STEMMING, VOTE),
        ):
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
        key = make_node_key("decision", DECISION_ID)
        detail = client.get(f"/api/decisions/{key}").json()
        assert (detail["dossier_numbers"], detail["chamber"]) == (["36774"], "TK")
        (row,) = client.get("/api/decisions").json()["items"]
        assert (row["dossier_numbers"], row["chamber"]) == (["36774"], "TK")
    finally:
        app.dependency_overrides.pop(get_store, None)
