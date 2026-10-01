"""What kind of dossier a dossier is comes from what it is: the Zaak.Soort of its own zaak.
Not from its neighbours' cases, and not from what is filed under it."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    RAW_KIND_TK_ACTIVITEIT,
    RAW_KIND_TK_DOSSIER,
    SOURCE_TK,
)
from lawgraph.core.models import make_node_key
from lawgraph.db import GraphStore, RawSourceWriter, raw_source_doc
from tests.integration.seed import seed, uid


def _zaak(number: int, kind: str, dossier: int) -> dict[str, Any]:
    # 36001 has the id of the seed's dossier 1
    return {
        "Id": uid(number, 2),
        "Nummer": f"2026Z{number:05d}",
        "Soort": kind,
        "Kamerstukdossier": [{"Id": uid(dossier % 36000, 3), "Nummer": dossier}],
    }


def _dossier(store: GraphStore, number: int) -> dict[str, Any]:
    doc = store.get_document("dossiers", make_node_key(str(number)))
    assert doc is not None
    return doc["props"]


def test_a_vote_on_many_dossiers_gives_each_only_the_kinds_of_its_own_cases(
    database: str, cli: Any
) -> None:
    """A Stemmingen covers every dossier voted on that day: an initiative bill on the
    agenda made a budget and a policy dossier initiative bills too."""
    store = GraphStore()
    seed(store, documents=0, judgments=0, regulations=0)
    votes = {
        "Id": uid(1, 11),
        "Nummer": "2026A00001",
        "Soort": "Stemmingen",
        "Datum": "2026-09-22T00:00:00+02:00",
        "Agendapunt": [
            {"Zaak": [_zaak(1, "Initiatiefwetgeving", 36001)]},
            {"Zaak": [_zaak(2, "Begroting", 36002), _zaak(3, "Motie", 36002)]},
            {"Zaak": [_zaak(4, "Motie", 36003)]},
            # the motions of the Algemene Politieke Beschouwingen, filed under the
            # Miljoenennota's number, and a letter on it
            {"Zaak": [_zaak(5, "Motie", 36004), _zaak(6, "Brief regering", 36004)]},
            # the fiches on new Commission proposals are EU by their number
            {"Zaak": [_zaak(7, "Motie", 22112)]},
        ],
    }
    miljoenennota = {
        "Id": uid(36004 - 36000, 3),
        "Nummer": 36004,
        "Toevoeging": None,
        "Titel": "Nota over de toestand van ’s Rijks Financiën",
    }
    # the seed titles every dossier as a bill
    policy_area = {
        "Id": uid(36003 - 36000, 3),
        "Nummer": 36003,
        "Toevoeging": None,
        "Titel": "Jeugdzorg",
    }
    fiches = {
        "Id": uid(22112, 3),
        "Nummer": 22112,
        "Toevoeging": None,
        "Titel": "Nieuwe Commissievoorstellen en initiatieven van de lidstaten van de "
        "Europese Unie",
    }
    with RawSourceWriter(store) as writer:
        for kind, payload in (
            (RAW_KIND_TK_ACTIVITEIT, votes),
            (RAW_KIND_TK_DOSSIER, policy_area),
            (RAW_KIND_TK_DOSSIER, miljoenennota),
            (RAW_KIND_TK_DOSSIER, fiches),
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

    bill, budget, policy, nota, eu = (
        _dossier(store, n) for n in (36001, 36002, 36003, 36004, 22112)
    )
    assert bill["case_kinds"] == ["Initiatiefwetgeving"]
    assert (bill["kind"], bill["kind_basis"]) == ("Initiatiefwetgeving", "case")
    # a Stemmingen activity is about every dossier on its agenda: it marks no phase
    assert [p["name"] for p in bill["phases"] if p["done"]] == []
    assert bill["current_phase"] is None
    assert budget["case_kinds"] == ["Begroting", "Motie"]
    assert budget["kind"] == "Begroting"
    assert policy["case_kinds"] == ["Motie"]
    # A motion filed under a dossier does not make it a motion, and no own name is given
    # to a dossier of letters and motions: it has no kind, and no phases.
    assert (policy["kind"], policy["kind_basis"]) == (None, None)
    assert policy["phases"] is None and policy["current_phase"] is None
    assert nota["case_kinds"] == ["Brief regering", "Motie"]
    assert (nota["kind"], nota["phases"]) == (None, None)
    assert eu["kind"] is None
