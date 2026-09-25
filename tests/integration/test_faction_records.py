"""A faction the Tweede Kamer holds under several Fractie records, one per period (50PLUS
2012-2021 and again from 2025): every record is the one faction, so a vote or a seat that names
any of its ids reaches it. The real ``normalize tk-dossiers`` on stored records."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    RAW_KIND_TK_FRACTIE,
    RAW_KIND_TK_FRACTIEZETELPERSOON,
    RAW_KIND_TK_PERSOON,
    RAW_KIND_TK_STEMMING,
    SOURCE_TK,
)
from lawgraph.core.models import make_node_key
from lawgraph.db import ArangoStore, RawSourceWriter, raw_source_doc
from tests.integration.seed import uid

OLD_50PLUS, NEW_50PLUS, VVD = uid(1, 8), uid(2, 8), uid(3, 8)
KROL = uid(1, 9)
DECISION = uid(1, 7)
CASE = {"Id": uid(1, 2), "Soort": "Motie", "Onderwerp": "Motie over pensioenen"}


def _vote(number: int, faction: str, label: str, choice: str, seats: int) -> dict:
    return {
        "Id": uid(number, 6),
        "Besluit_Id": DECISION,
        "Soort": choice,
        "FractieGrootte": seats,
        "ActorFractie": label,
        # the Kamer still names the record of 2012 on a vote of 2026
        "Fractie_Id": faction,
        "Persoon_Id": None,
        "GewijzigdOp": "2026-09-23T09:00:00+02:00",
        "Besluit": {
            "Id": DECISION,
            "BesluitSoort": "Stemmen - verworpen",
            "BesluitTekst": "Verworpen.",
            "AgendapuntZaakBesluitVolgorde": 1,
            "Zaak": [CASE],
            "Agendapunt": {
                "Onderwerp": CASE["Onderwerp"],
                "Zaak": [CASE],
                "Activiteit": {"Datum": "2026-09-22T00:00:00+02:00"},
            },
        },
    }


def _records() -> list[tuple[str, dict[str, Any]]]:
    return [
        (
            RAW_KIND_TK_FRACTIE,
            {
                "Id": OLD_50PLUS,
                "Afkorting": "50PLUS",
                "NaamNL": "50PLUS",
                "DatumActief": "2012-09-20T00:00:00+02:00",
                "DatumInactief": "2021-05-11T00:00:00+02:00",
                "GewijzigdOp": "2021-05-11T00:00:00+02:00",
            },
        ),
        (
            RAW_KIND_TK_FRACTIE,
            {
                "Id": NEW_50PLUS,
                "Afkorting": "50PLUS",
                "NaamNL": "50PLUS",
                "DatumActief": "2025-11-12T00:00:00+01:00",
                "DatumInactief": None,
                "GewijzigdOp": "2025-11-12T00:00:00+01:00",
            },
        ),
        (RAW_KIND_TK_FRACTIE, {"Id": VVD, "Afkorting": "VVD", "NaamNL": "VVD"}),
        (RAW_KIND_TK_PERSOON, {"Id": KROL, "Voornamen": "Henk", "Achternaam": "Krol"}),
        (
            RAW_KIND_TK_FRACTIEZETELPERSOON,
            {
                "Id": uid(1, 5),
                "Persoon_Id": KROL,
                "FractieZetel": {"Fractie_Id": OLD_50PLUS},
                "Van": "2012-09-20T00:00:00+02:00",
                "TotEnMet": "2017-03-22T00:00:00+01:00",
                "Functie": "Lid",
            },
        ),
        (RAW_KIND_TK_STEMMING, _vote(1, OLD_50PLUS, "50PLUS", "Tegen", 2)),
        (RAW_KIND_TK_STEMMING, _vote(2, VVD, "VVD", "Voor", 22)),
    ]


def test_every_record_of_a_faction_is_that_faction(database: str, cli: Any) -> None:
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

    faction = store.get_node("factions", "50plus")
    assert faction is not None
    # the faction spans both records: seated from 2012, and seated now
    assert faction.props["active_from"] == "2012-09-20"
    assert faction.props["active"] is True
    assert sorted(faction.props["external_ids"]) == sorted([OLD_50PLUS, NEW_50PLUS])

    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        decision_key = make_node_key(f"decision_{DECISION}")
        decision = client.get(f"/api/decisions/{decision_key}").json()
        krol = client.get(f"/api/members/{make_node_key(KROL)}").json()
    finally:
        app.dependency_overrides.pop(get_store, None)

    # the votes add up to the tally: 50PLUS is among them
    assert {v["voter_key"]: v["seats"] for v in decision["votes"]} == {
        "50plus": 2,
        "vvd": 22,
    }
    assert sum(v["seats"] for v in decision["votes"]) == sum(decision["tally"].values())
    # a seat of 2012 on the old record is a membership of the faction
    assert [m["faction_key"] for m in krol["faction_memberships"]] == ["50plus"]


def test_a_vote_of_a_faction_the_graph_lacks_is_reported(
    database: str, cli: Any
) -> None:
    store = ArangoStore()
    with RawSourceWriter(store) as writer:
        for kind, payload in _records():
            if payload["Id"] == VVD:  # the VVD record is not loaded
                continue
            writer.add(
                raw_source_doc(
                    source=SOURCE_TK,
                    kind=kind,
                    external_id=payload["Id"],
                    payload_json=payload,
                )
            )
    done = cli("normalize", "tk-dossiers")
    assert "do not add up to the tally; the factions: VVD." in done.stderr + done.stdout
