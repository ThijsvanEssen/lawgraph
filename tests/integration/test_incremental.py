"""An incremental run must find in the database what is not in its window."""

from __future__ import annotations

import datetime as dt
import time
from typing import Any

from lawgraph.config.constants import (
    RAW_KIND_TK_ACTIVITEIT,
    RAW_KIND_TK_FRACTIE,
    RAW_KIND_TK_STEMMING,
    RELATION_VOTED,
    SOURCE_TK,
)
from lawgraph.core.models import make_node_key
from lawgraph.db import ArangoStore, RawSourceWriter, raw_source_doc
from tests.integration.seed import FACTIONS, seed, uid


def _voted_edges(store: ArangoStore) -> int:
    aql = "FOR e IN edges FILTER e.relation == @relation COLLECT WITH COUNT INTO n RETURN n"
    return next(iter(store.query(aql, {"relation": RELATION_VOTED})))


def test_votes_of_a_new_decision_are_linked_to_factions_loaded_earlier(
    database: str, cli: Any
) -> None:
    """`retrieve all` skips the members and factions on incremental runs (--skip-members)."""
    store = ArangoStore()
    seed(store, documents=120, judgments=1, regulations=1)
    cli("normalize", "tk-dossiers")
    before = _voted_edges(store)
    assert before > 0

    time.sleep(1.1)  # fetched_at has a precision of a second
    window = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    decision = uid(999_999, 7)
    with RawSourceWriter(store) as writer:
        for number in range(FACTIONS):
            vote = {
                "Id": uid(900_000 + number, 6),
                "Besluit_Id": decision,
                "Soort": "Voor",
                "FractieGrootte": 10,
                "ActorFractie": f"Fractie {number}",
                "Fractie_Id": uid(number, 8),
                "GewijzigdOp": "2025-06-01T10:00:00+02:00",
                "Besluit": {"Id": decision, "BesluitSoort": "Stemmen - aangenomen"},
            }
            writer.add(
                raw_source_doc(
                    source=SOURCE_TK,
                    kind=RAW_KIND_TK_STEMMING,
                    external_id=vote["Id"],
                    payload_json=vote,
                )
            )

    cli("normalize", "tk-dossiers", "--since", window.isoformat())
    assert _voted_edges(store) == before + FACTIONS


def _store_tk(store: ArangoStore, kind: str, payloads: list[dict[str, Any]]) -> None:
    with RawSourceWriter(store) as writer:
        for payload in payloads:
            writer.add(
                raw_source_doc(
                    source=SOURCE_TK,
                    kind=kind,
                    external_id=payload["Id"],
                    payload_json=payload,
                )
            )


def _vote(number: int, decision: str, label: str, faction: int) -> dict[str, Any]:
    return {
        "Id": uid(number, 6),
        "Besluit_Id": decision,
        "Soort": "Voor",
        "FractieGrootte": 10,
        "ActorFractie": label,
        "Fractie_Id": uid(faction, 8),
        "GewijzigdOp": "2025-06-01T10:00:00+02:00",
        "Besluit": {"Id": decision, "BesluitSoort": "Stemmen - aangenomen"},
    }


def _window() -> str:
    time.sleep(1.1)  # fetched_at has a precision of a second
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def test_a_window_without_votes_keeps_the_spellings_votes_gave_a_faction(
    database: str, cli: Any
) -> None:
    """Retrieve reads the factions again on every run, so an incremental normalize writes
    them all again; the acronym of a party counts only when a vote used it."""
    store = ArangoStore()
    party = {"Id": uid(500, 8), "Afkorting": "Partij voor de Dieren", "NaamNL": ""}
    party["NaamNL"] = party["Afkorting"]
    _store_tk(store, RAW_KIND_TK_FRACTIE, [party])
    _store_tk(store, RAW_KIND_TK_STEMMING, [_vote(1, uid(1, 7), "PVDD", 500)])
    cli("normalize", "tk-dossiers")
    key = make_node_key(party["Afkorting"])
    assert "PVDD" in store.db.collection("factions").get(key)["props"]["aliases"]

    window = _window()
    _store_tk(store, RAW_KIND_TK_FRACTIE, [party])  # read again, no vote since
    cli("normalize", "tk-dossiers", "--since", window)
    assert "PVDD" in store.db.collection("factions").get(key)["props"]["aliases"]


def test_a_vote_that_changed_does_not_make_its_decision_a_decision_of_one(
    database: str, cli: Any
) -> None:
    store = ArangoStore()
    seed(store, documents=0, judgments=0, regulations=0)  # the factions
    decision = uid(77, 7)
    votes = [_vote(100 + n, decision, f"Fractie {n}", n) for n in range(FACTIONS)]
    _store_tk(store, RAW_KIND_TK_STEMMING, votes)
    cli("normalize", "tk-dossiers")
    key = make_node_key("decision", decision)
    assert store.db.collection("decisions").get(key)["props"]["tally"] == {
        "Voor": 10 * FACTIONS
    }

    window = _window()
    _store_tk(store, RAW_KIND_TK_STEMMING, [votes[0] | {"Soort": "Tegen"}])
    cli("normalize", "tk-dossiers", "--since", window)
    assert store.db.collection("decisions").get(key)["props"]["tally"] == {
        "Voor": 10 * (FACTIONS - 1),
        "Tegen": 10,
    }


def test_an_activity_in_the_window_adds_to_the_case_kinds_of_its_dossier(
    database: str, cli: Any
) -> None:
    store = ArangoStore()
    seed(store, documents=20, judgments=0, regulations=0)  # activities on dossier 36000
    cli("normalize", "tk-dossiers")
    key = make_node_key("36000")
    before = store.db.collection("dossiers").get(key)["props"]["case_kinds"]
    assert before

    window = _window()
    activity = {
        "Id": uid(4242, 11),
        "Nummer": "2025A99999",
        "Soort": "Plenair debat",
        "Datum": "2025-06-02T00:00:00+02:00",
        "Agendapunt": [
            {
                "Zaak": [
                    {
                        "Id": uid(4242, 2),
                        "Nummer": "2025Z99999",
                        "Soort": "Amendement",
                        "Kamerstukdossier": [{"Id": uid(0, 3), "Nummer": 36000}],
                    }
                ]
            }
        ],
    }
    _store_tk(store, RAW_KIND_TK_ACTIVITEIT, [activity])
    cli("normalize", "tk-dossiers", "--since", window)
    after = store.db.collection("dossiers").get(key)["props"]["case_kinds"]
    assert set(after) == set(before) | {"Amendement"}


def test_a_rerun_replaces_a_tally_it_does_not_add_to_it(
    database: str, cli: Any
) -> None:
    """An update merges nested objects unless told not to: a choice nobody made any more
    stayed in the tally for good, also on a full run."""
    store = ArangoStore()
    seed(store, documents=0, judgments=0, regulations=0)
    decision = uid(78, 7)
    votes = [_vote(200 + n, decision, f"Fractie {n}", n) for n in range(FACTIONS)]
    _store_tk(store, RAW_KIND_TK_STEMMING, votes)
    cli("normalize", "tk-dossiers")

    _store_tk(store, RAW_KIND_TK_STEMMING, [v | {"Soort": "Tegen"} for v in votes])
    cli("normalize", "tk-dossiers")
    props = store.db.collection("decisions").get(make_node_key("decision", decision))
    assert props["props"]["tally"] == {"Tegen": 10 * FACTIONS}
    assert props["props"]["voters"] == {"Tegen": FACTIONS}
