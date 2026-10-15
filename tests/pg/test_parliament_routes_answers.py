"""The answers of the routes of committees, members, factions, ministries, cabinets,
commitments, parties and the seats of the Kamers on a real PostgreSQL, exactly as pinned in
``parliament_routes.json``: a route that moves to another module answers the same."""

from __future__ import annotations

import json
import pathlib
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.db import GraphStore
from tests.pg.cabinet_graph import government_graph
from tests.pg.committee_graph import (
    Graph,
    authorship_graph,
    committee_graph,
    faction_graph,
    people_graph,
    write_votes,
)

PINNED = pathlib.Path(__file__).with_name("parliament_routes.json")


def ek_votes_graph(store: GraphStore) -> None:
    """A faction of the Eerste Kamer and the votes of the Eerste Kamer that name it."""
    g = Graph(store)
    g.node("factions", "ek_vvd", name="VVD", abbreviation="VVD", chamber="EK")
    g.node("factions", "tk_vvd", name="VVD", abbreviation="VVD")
    decisions: dict[str, dict[str, Any]] = {
        "e1": {
            "date": "2024-02-01",
            "factions_for": ["VVD", "D66"],
            "dossier_numbers": ["36000"],
            "result": "Aangenomen",
            "bill_decision": True,
        },
        "e2": {"date": "2024-02-01", "factions_against": ["VVD"]},
        "e3": {"factions_noted": ["VVD"]},
        "e4": {"date": "2020-01-01", "factions_for": ["VVD"]},
    }
    for key, props in decisions.items():
        g.node("decisions", key, ["EK"], chamber="EK", **props)
    g.write()


def committee_routes_graph(store: GraphStore) -> None:
    """``committee_graph`` with a seat a member list can show: one that ends on a day."""
    committee_graph(store)
    g = Graph(store)
    g.edge("members/m6", "MEMBER_OF", "committees/c_b", to_date="2001-01-01")
    g.write()


def touched_graph(store: GraphStore) -> None:
    """What the members and factions of ``authorship_graph`` changed in two laws."""
    authorship_graph(store)
    g = Graph(store)
    g.node("instruments", "i1", display_name="Wet 1", bwb_id="BWBR1", title="Een")
    g.edge("documents/old", "AMENDS", "articles/a1")
    g.edge("documents/new", "INTRODUCES", "articles/a1")
    g.edge("articles/a1", "PART_OF", "instruments/i1")
    g.write()


# Each graph and the addresses asked of it.
SCENARIOS: dict[str, tuple[Callable[[GraphStore], None], list[str]]] = {
    "committees": (
        committee_routes_graph,
        [
            "/api/committees",
            "/api/committees?chamber=EK",
            "/api/committees?active_from=2000-01-01&active_to=2030-01-01",
            "/api/committees/b",
            "/api/committees/c_b?current_only=false&status=closed",
            "/api/committees/b?status=open&limit=1&offset=1",
            "/api/committees/b/activities?limit=2",
            "/api/committees/b/activities?offset=1&limit=2",
            "/api/committees/nope",
            "/api/committees/nope/activities",
            "/api/members/m5",
        ],
    ),
    "people": (
        people_graph,
        [
            "/api/members",
            "/api/members?include_all=true",
            "/api/members?capacity=bewindspersoon",
            "/api/members?cabinet=cab1",
            "/api/members?party=vvd",
            "/api/members?party=d66&active=true",
            "/api/members?party=democraten%2066",
            "/api/members?q=emile&include_all=true",
            "/api/members?sort=family_name&include_all=true",
            "/api/members?active_from=2015-01-01&active_to=2016-01-01",
            "/api/members?slug=nope",
            "/api/members?limit=2&offset=1",
            "/api/members?chamber=EK",
            "/api/members?chamber=EK&active=true",
            "/api/members?chamber=EK&party=VVD&q=emile",
            "/api/members?chamber=EK&active_from=2024-01-01",
            "/api/members/m7",
            "/api/members/nope",
        ],
    ),
    "factions": (
        faction_graph,
        [
            "/api/factions",
            "/api/factions?active=true",
            "/api/factions?active=false",
            "/api/factions?q=d6",
            "/api/factions?chamber=EK",
            "/api/factions?active_from=2015-01-01",
            "/api/factions/vvd",
            "/api/factions/nope",
            "/api/factions/vvd/votes",
            "/api/parliament/seats",
            "/api/parliament/seats?date=2015-01-01",
        ],
    ),
    "votes": (
        write_votes,
        [
            "/api/members/m1/votes",
            "/api/members/m1/votes?limit=2&offset=1",
            "/api/members/m1/votes?in_office=true",
            "/api/members/nope/votes",
        ],
    ),
    "ek_votes": (
        ek_votes_graph,
        [
            "/api/factions/ek_vvd/votes",
            "/api/factions/ek_vvd/votes?from=2021-01-01",
            "/api/factions/ek_vvd/votes?to=2023-12-31&limit=1&offset=1",
            "/api/factions/tk_vvd/votes",
        ],
    ),
    "authorship": (
        touched_graph,
        [
            "/api/members/m1/dossiers",
            "/api/members/m1/dossiers?limit=1&offset=1",
            "/api/members/m2/dossiers",
            "/api/factions/vvd/dossiers",
            "/api/factions/d66/dossiers",
            "/api/members/m1/touched-instruments",
            "/api/members/m2/touched-instruments?limit=1",
            "/api/factions/vvd/touched-instruments",
            "/api/members/nope/dossiers",
            "/api/factions/nope/touched-instruments",
        ],
    ),
    "government": (
        government_graph,
        [
            "/api/cabinets",
            "/api/cabinets/jetten",
            "/api/cabinets/schoof",
            "/api/cabinets/nope",
            "/api/cabinets/jetten/seats",
            "/api/cabinets/nope/seats",
            "/api/commitments",
            "/api/commitments?status=Openstaand&ministry=fin",
            "/api/commitments?member=m1&sort=expected_resolution",
            "/api/commitments?cabinet=schoof&q=ecole",
            "/api/commitments?dossier=36000&facets=false",
            "/api/commitments?overdue=true&due_before=2030-01-01",
            "/api/commitments?from=2026-04-02&to=2026-04-30",
            "/api/commitments?limit=1&offset=1",
            "/api/commitments/k1",
            "/api/commitments/nope",
            "/api/members?capacity=bewindspersoon",
            "/api/members?cabinet=jetten&include_all=true",
        ],
    ),
}


def answers(store: GraphStore, scenario: str) -> dict[str, Any]:
    """The status and body of each address of *scenario*, on its graph in *store*."""
    write, urls = SCENARIOS[scenario]
    write(store)
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        return {
            url: {"status": answer.status_code, "body": answer.json()}
            for url in urls
            for answer in [client.get(url)]
        }
    finally:
        app.dependency_overrides.pop(get_store, None)


@pytest.fixture(scope="module")
def pinned() -> Iterator[dict[str, Any]]:
    yield json.loads(PINNED.read_text())


@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_the_routes_answer_as_pinned(
    store: GraphStore, pinned: dict[str, Any], scenario: str
) -> None:
    # in the order of the keys too
    assert json.dumps(answers(store, scenario)) == json.dumps(pinned[scenario])
