"""What kind of dossier a dossier is comes from its own cases, not from its neighbours'."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import RAW_KIND_TK_ACTIVITEIT, SOURCE_TK
from lawgraph.core.models import make_node_key
from lawgraph.db import ArangoStore, RawSourceWriter, raw_source_doc
from tests.integration.seed import seed, uid


def _zaak(number: int, kind: str, dossier: int) -> dict[str, Any]:
    return {
        "Id": uid(number, 2),
        "Nummer": f"2026Z{number:05d}",
        "Soort": kind,
        "Kamerstukdossier": [{"Id": uid(dossier - 36000, 3), "Nummer": dossier}],
    }


def _dossier(store: ArangoStore, number: int) -> dict[str, Any]:
    return store.db.collection("dossiers").get(make_node_key(str(number)))["props"]


def test_a_vote_on_many_dossiers_gives_each_only_the_kinds_of_its_own_cases(
    database: str, cli: Any
) -> None:
    """A Stemmingen covers every dossier voted on that day: an initiative bill on the
    agenda made a budget and a policy dossier initiative bills too."""
    store = ArangoStore()
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
        ],
    }
    with RawSourceWriter(store) as writer:
        writer.add(
            raw_source_doc(
                source=SOURCE_TK,
                kind=RAW_KIND_TK_ACTIVITEIT,
                external_id=votes["Id"],
                payload_json=votes,
            )
        )

    cli("normalize", "tk-dossiers")

    bill, budget, policy = (_dossier(store, n) for n in (36001, 36002, 36003))
    assert bill["case_kinds"] == ["Initiatiefwetgeving"]
    assert bill["track_kind"] == "initiatiefwetsvoorstel"
    assert bill["current_stage"] == "stemming"
    assert budget["case_kinds"] == ["Begroting", "Motie"]
    assert budget["track_kind"] == "begroting"
    assert policy["case_kinds"] == ["Motie"]
    assert policy["track_kind"] == "motie"
    # The stages are those of a bill: a policy dossier has none.
    assert policy["current_stage"] is None
    assert policy["stages_present"] == []
