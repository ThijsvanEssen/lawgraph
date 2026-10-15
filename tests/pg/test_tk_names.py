"""``normalize tk-dossiers --factions`` and ``--committees``: every stored Fractie and
Commissie record again, with the names and roles in the one form the source gives them."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    COLLECTION_COMMITTEES,
    COLLECTION_FACTIONS,
    COLLECTION_MEMBERS,
    RAW_KIND_TK_COMMISSIE,
    RAW_KIND_TK_FRACTIE,
    RAW_KIND_TK_STEMMING,
    RELATION_MEMBER_OF,
)
from lawgraph.db import GraphStore
from lawgraph.pipelines.normalize.tk_dossiers import TKDossiersNormalizePipeline
from tests.integration.seed import write_tk


def _store_raw(store: GraphStore, kind: str, *payloads: dict[str, Any]) -> None:
    write_tk(store, [(kind, payload) for payload in payloads])


def _vote(vote_id: str, faction_id: str, label: str) -> dict[str, Any]:
    return {
        "Id": vote_id,
        "Besluit_Id": "b-1",
        "Fractie_Id": faction_id,
        "ActorFractie": label,
    }


def test_a_faction_is_named_by_its_own_votes_only(store: GraphStore) -> None:
    """Nieuw Sociaal Contract, whose Afkorting is its full name, goes by the NSC of its
    votes; Groep Lazrak does not take the GL GroenLinks votes as."""
    _store_raw(
        store,
        RAW_KIND_TK_FRACTIE,
        {
            "Id": "f-nsc",
            "Afkorting": "Nieuw Sociaal Contract",
            "NaamNL": "Nieuw Sociaal Contract",
        },
        {"Id": "f-gl", "Afkorting": "GL", "NaamNL": "GroenLinks"},
        {"Id": "f-lazrak", "Afkorting": "Groep Lazrak", "NaamNL": "Groep Lazrak"},
    )
    _store_raw(
        store,
        RAW_KIND_TK_STEMMING,
        _vote("v-1", "f-nsc", "NSC"),
        _vote("v-2", "f-gl", "GL"),
        _vote("v-3", "f-lazrak", "Groep Lazrak"),
    )
    TKDossiersNormalizePipeline(store=store, factions=True).run()
    props = {
        key: store.get_document(COLLECTION_FACTIONS, key)["props"]  # type: ignore[index]
        for key in ("nieuw_sociaal_contract", "gl", "groep_lazrak")
    }
    assert props["nieuw_sociaal_contract"]["abbreviation"] == "NSC"
    assert props["nieuw_sociaal_contract"]["aliases"] == [
        "NSC",
        "Nieuw Sociaal Contract",
    ]
    assert props["gl"]["aliases"] == ["GL", "GroenLinks"]
    assert props["groep_lazrak"]["abbreviation"] == "Groep Lazrak"
    assert props["groep_lazrak"]["aliases"] == ["Groep Lazrak"]


def test_a_committee_seat_has_one_spelling_of_its_role(store: GraphStore) -> None:
    """The Kamer writes ``Plv. lid`` on older seats and ``PlvLid`` on newer ones."""
    store.bulk_insert_or_update_nodes(
        COLLECTION_MEMBERS,
        [
            {"key": key, "type": "member", "labels": [], "props": {"name": key}}
            for key in ("p_old", "p_new")
        ],
    )
    _store_raw(
        store,
        RAW_KIND_TK_COMMISSIE,
        {
            "Id": "c-fin",
            "NaamNL": "Vaste commissie voor Financiën",
            "Afkorting": "FIN",
            "CommissieZetel": [
                {
                    "CommissieZetelVervangerPersoon": [
                        {
                            "Persoon_Id": "p-old",
                            "Van": "2023-12-13",
                            "Functie": "Plv. lid",
                        },
                        {
                            "Persoon_Id": "p-new",
                            "Van": "2025-11-18",
                            "Functie": "PlvLid",
                        },
                    ]
                }
            ],
        },
    )
    TKDossiersNormalizePipeline(store=store, committees=True).run()
    assert store.get_document(COLLECTION_COMMITTEES, "c_fin") is not None
    roles = {
        row["member"]: row["role"]
        for row in store.query(
            "SELECT from_id AS member, doc -> 'meta' ->> 'role' AS role FROM edges"
            " WHERE relation = %(relation)s",
            {"relation": RELATION_MEMBER_OF},
        )
    }
    assert roles == {"members/p_old": "PlvLid", "members/p_new": "PlvLid"}
