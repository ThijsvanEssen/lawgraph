"""The edges the TK and EK linkers write through their shared helpers: the VOTED edges of a
decision derived in full (a voter gone from the list loses its edge), and AUTHORED with
the same meta from a paper and from a case."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.config.constants import (
    COLLECTION_CASES,
    COLLECTION_DECISIONS,
    COLLECTION_DOCUMENTS,
    COLLECTION_MEMBERS,
    RELATION_VOTED,
)
from lawgraph.core.models import Node
from lawgraph.core.tk_records.actors import case_actors, document_actors
from lawgraph.db.queries import removals
from lawgraph.db.queries.normalize import eerstekamer as normalize_ek
from lawgraph.pipelines.normalize import _tk_cases as tk_cases
from lawgraph.pipelines.normalize import eerstekamer_votes
from lawgraph.pipelines.normalize.tk_case_actors import link_case_actors
from tests.fakes import InMemoryStore


def _faction(name: str, seats: int) -> dict[str, Any]:
    return {
        "id": f"factions/ek_{name.lower()}",
        "abbreviation": name,
        "seats": seats,
        "observed_from": "2026-01-01",
        "observed_until": None,
    }


def _edges(store: InMemoryStore) -> list[tuple[str, str, str, str, dict[str, Any]]]:
    return sorted(
        (e["from_id"], e["relation"], e["to_id"], e["source"], e["meta"])
        for e in store.edges.values()
    )


@pytest.fixture()
def kept(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, list[str]]]:
    """What each call of ``remove_edges_into_except`` keeps per decision."""
    calls: list[dict[str, list[str]]] = []
    monkeypatch.setattr(
        removals,
        "remove_edges_into_except",
        lambda _store, relation, written: calls.append(written) or 0,
    )
    return calls


def test_an_ek_faction_gone_from_the_list_of_a_vote_loses_its_edge(
    monkeypatch: pytest.MonkeyPatch, kept: list[dict[str, list[str]]]
) -> None:
    factions = [_faction("PVV", 4), _faction("VVD", 10), _faction("SP", 3)]
    monkeypatch.setattr(normalize_ek, "ek_factions", lambda _s: factions)
    store = InMemoryStore()
    pipeline = eerstekamer_votes.EerstekamerVotesNormalizePipeline(store=store)  # type: ignore[arg-type]

    def vote(**lists: list[str]) -> Node:
        return Node(
            collection=COLLECTION_DECISIONS,
            key="ek_1",
            props={"date": "2026-10-06", **lists},
        )

    eerstekamer_votes.link_faction_votes(
        pipeline,
        [vote(factions_for=["PVV"], factions_against=["VVD"], factions_noted=["SP"])],
        source="test",
    )
    assert _edges(store) == [
        (
            "factions/ek_pvv",
            RELATION_VOTED,
            "decisions/ek_1",
            "test",
            {"choice": "Voor", "seats": 4},
        ),
        (
            "factions/ek_sp",
            RELATION_VOTED,
            "decisions/ek_1",
            "test",
            {"choice": "Aantekening gevraagd", "seats": 3},
        ),
        (
            "factions/ek_vvd",
            RELATION_VOTED,
            "decisions/ek_1",
            "test",
            {"choice": "Tegen", "seats": 10},
        ),
    ]
    assert {key for keys in kept[0].values() for key in keys} == set(store.edges)

    store.edges.clear()
    eerstekamer_votes.link_faction_votes(
        pipeline, [vote(factions_for=["PVV"])], source="test"
    )
    # PVV alone is kept on the decision: the edges of VVD and SP go
    assert kept[1] == {"decisions/ek_1": list(store.edges)}
    assert [edge["from_id"] for edge in store.edges.values()] == ["factions/ek_pvv"]


def test_a_member_signs_a_paper_and_submits_a_case_with_the_same_meta() -> None:
    store = InMemoryStore(
        {
            COLLECTION_MEMBERS: [{"key": "p_1", "props": {}}],
            COLLECTION_CASES: [{"key": "z_1", "props": {}}],
        }
    )
    actor = {"Relatie": "Indiener", "Persoon_Id": "p-1", "Functie": "minister"}
    paper = Node.skeleton(
        COLLECTION_DOCUMENTS,
        "d_1",
        {"actors": document_actors({"DocumentActor": [actor]})},
    )

    tk_cases.link_authors(store, {"d-1": paper}, source="test")
    link_case_actors(
        store,
        [("z-1", case_actors({"ZaakActor": [actor]}))],
        source="test",
    )

    assert _edges(store) == [
        (
            "members/p_1",
            "AUTHORED",
            "cases/z_1",
            "test",
            {"role": "Indiener", "function": "minister", "capacity": "bewindspersoon"},
        ),
        (
            "members/p_1",
            "AUTHORED",
            "documents/d_1",
            "test",
            {"role": "Indiener", "function": "minister", "capacity": "bewindspersoon"},
        ),
    ]
