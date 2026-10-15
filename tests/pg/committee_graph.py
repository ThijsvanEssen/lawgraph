"""The graph of members, factions, committees, their votes and what they signed, written
for the queries of committees and members and shared by their test modules."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.config.constants import (
    RELATION_ABOUT,
    RELATION_AUTHORED,
    RELATION_LED_BY,
    RELATION_MEMBER_OF,
    RELATION_PART_OF,
    RELATION_VOTED,
)
from lawgraph.core.tk_records.decisions import VOTE_KIND_MEMBER
from lawgraph.db import GraphStore, make_edge_doc
from lawgraph.db.queries.member_votes import get_member_votes
from tests.pg.plans import explain, plan_nodes, recorded

FIRST = "Eerste ondertekenaar"
CO = "Mede ondertekenaar"


class Graph:
    """Nodes and edges written straight into the test database."""

    def __init__(self, store: GraphStore) -> None:
        self.store = store
        self._nodes: dict[str, list[dict[str, Any]]] = {}
        self._edges: list[dict[str, Any]] = []

    def node(
        self, collection: str, key: str, labels: list[str] | None = None, **props: Any
    ) -> str:
        self._nodes.setdefault(collection, []).append(
            {
                "_key": key,
                "type": collection[:-1],
                "labels": labels or [],
                "props": props,
            }
        )
        return f"{collection}/{key}"

    def edge(
        self,
        from_id: str,
        relation: str,
        to_id: str,
        *,
        status: str = "canoniek",
        **meta: Any,
    ) -> None:
        self._edges.append(
            make_edge_doc(from_id, to_id, relation, status=status, meta=meta)
        )

    def write(self) -> None:
        for collection, docs in self._nodes.items():
            self.store.bulk_insert_or_update_nodes(collection, docs)
        self.store.bulk_insert_or_update_edges(self._edges)
        self._nodes, self._edges = {}, []


def committee_graph(store: GraphStore) -> None:
    g = Graph(store)
    committee = g.node("committees", "c_b", name="Commissie B", slug="b")
    g.node("committees", "zz", name="Zeta", slug="x")
    g.node("committees", "x", name="Ix", slug="ix")
    for key, name in (("m1", "Anna"), ("m2", "Anna"), ("Zz", "Anna"), ("m3", None)):
        member = g.node("members", key, name=name)
        g.edge(member, RELATION_MEMBER_OF, committee)
    g.node("members", "m4", name="Bert")
    g.node("members", "m5", name="Carla")
    g.node("members", "m6", name="Dirk")
    g._edges = [edge for edge in g._edges if edge["_from"] != "members/m2"]
    g.edge("members/m2", RELATION_MEMBER_OF, committee, to_date="2000-01-01")
    g.edge("members/m4", RELATION_MEMBER_OF, committee, observed_until="2024-01-01")
    g.edge(
        "members/m5",
        RELATION_MEMBER_OF,
        committee,
        from_date="2020-01-01",
        to_date="2999-01-01",
        role="voorzitter",
        observed_from="2020-02-01",
    )
    g.edge("members/m6", RELATION_MEMBER_OF, committee, to_date=5)
    dossiers = {
        "d1": {"opened_on": "2024-01-01"},
        "d2": {"opened_on": "2024-01-01"},
        "d3": {},
        "d4": {"opened_on": "2023-01-01", "closed": True},
        "d5": {"opened_on": "2020-01-01", "closed": "true"},
    }
    for key, props in dossiers.items():
        g.node("dossiers", key, number=key, **props)
    activities = {
        "a1": {"date": "2024-01-01", "dossier_numbers": ["36000"], "kind": "Debat"},
        "a2": {"date": "2024-01-01", "dossier_numbers": []},
        "a3": {"agenda_title": "Zonder datum"},
        "a5": {"date": "2023-01-01", "dossier_numbers": ""},
        "a6": {"date": "2022-01-01", "dossier_numbers": {}},
    }
    for key, props in activities.items():
        activity = g.node("activities", key, **props)
        g.edge(activity, RELATION_LED_BY, committee)
    for activity, about in (
        ("a1", "dossiers/d1"),
        ("a1", "dossiers/d2"),
        ("a2", "dossiers/d3"),
        ("a2", "dossiers/d1"),
        ("a3", "cases/k1"),
        ("a5", "dossiers/d4"),
        ("a5", "dossiers/d5"),
        ("a6", "dossiers/gone"),
    ):
        g.edge(f"activities/{activity}", RELATION_ABOUT, about)
    g.write()


VVD = {
    "faction_id": "factions/vvd",
    "faction_key": "vvd",
    "abbreviation": "VVD",
    "name": "Volkspartij",
    "from_date": "2010-01-01",
    "to_date": "2019-12-31",
}


D66 = {
    "faction_id": "factions/d66",
    "faction_key": "d66",
    "abbreviation": "D66",
    "from_date": "2020-01-01",
    "to_date": None,
    "aliases": ["Democraten 66"],
}


def people_graph(store: GraphStore) -> None:
    """Members with and without a name, seat, party, post and seat in the Eerste Kamer."""
    g = Graph(store)
    g.node("members", "m1", name="Anna", party="D66", faction_memberships=[VVD, D66])
    g.node("members", "m2", name="Anna", faction_memberships=[{**VVD, "to_date": None}])
    g.node("members", "Zz", name="Anna", faction_memberships=[{**VVD, "to_date": None}])
    # "" is no name: the next one is
    g.node("members", "m3", name="", known_as="Bert", faction_memberships=[VVD])
    g.node(
        "members",
        "m4",
        government_name="C. de Vries",
        government_functions=[{"cabinet_key": "cab1"}],
    )
    g.node("members", "m5", name=None, faction_memberships=[VVD])
    g.node(
        "members",
        "m6",
        name="Émile",
        faction_memberships=[D66],
        ek={"abbreviation": "VVD", "name": "Émile E.", "observed_until": None},
    )
    g.node(
        "members",
        "m7",
        name="Zoë",
        ek={"abbreviation": "GL-PvdA", "observed_until": "2024-06-01"},
        government_functions=[{"cabinet_key": "cab2"}, {"cabinet_key": "cab1"}],
    )
    g.node("members", "m8", ek={"abbreviation": "vvd"})
    g.node("members", "m9", name="ÉMILE twee", faction_memberships=[])
    g.write()


def faction_graph(store: GraphStore) -> None:
    """Factions of both Kamers, seated and not, with members seated, gone and leaving."""
    g = Graph(store)
    g.node("factions", "vvd", name="VVD", abbreviation="VVD", active=True, seats=24)
    g.node("factions", "z", name="Zeta", abbreviation="D66", active=True)
    g.node("factions", "d66", name="D66", abbreviation="D66", active=True)
    g.node("factions", "cda", name="CDA", abbreviation=None, active=False)
    g.node("factions", "nameless", name="", abbreviation="X", active=True)
    g.node("factions", "none", name="Geen", active=None)
    g.node(
        "factions", "ek_vvd", name="VVD", abbreviation="VVD", active=True, chamber="EK"
    )
    for member in ("m1", "m2", "m3", "m4", "m5"):
        g.node("members", member, name=member)
    g.edge("members/m1", RELATION_MEMBER_OF, "factions/vvd")
    g.edge("members/m2", RELATION_MEMBER_OF, "factions/vvd", observed_until=None)
    g.edge("members/m3", RELATION_MEMBER_OF, "factions/vvd", observed_until="2020")
    # a former member (last day past) is not counted, one leaving later still is
    g.edge("members/m4", RELATION_MEMBER_OF, "factions/vvd", to_date="2017-03-22")
    g.edge("members/m5", RELATION_MEMBER_OF, "factions/vvd", to_date="2999-12-31")
    g.edge("members/m3", RELATION_MEMBER_OF, "factions/ek_vvd", chamber="EK")
    g.edge("members/m1", RELATION_MEMBER_OF, "factions/d66")
    g.write()


def write_votes(store: GraphStore) -> None:
    g = Graph(store)
    g.node("members", "m1", name="Anna", party="D66", faction_memberships=[VVD, D66])
    g.node("factions", "vvd", name="VVD")
    g.node("factions", "d66", name="D66")
    decisions = {
        "s1": {"date": "2024-01-01", "decision_id": "b1", "subject": "Motie"},
        "s2": {"date": "2015-06-01", "passed": False},
        "s3": {"date": "2024-01-01", "vote_kind": VOTE_KIND_MEMBER},
        "s4": {"subject": "Zonder datum"},
        "s5": {"date": "2018-01-01"},
        "s0": {"date": "2024-01-01", "passed": True},
    }
    for key, props in decisions.items():
        g.node("decisions", key, **props)
    for voter, decision, choice, seats in (
        ("factions/vvd", "s1", "Voor", 24),
        ("factions/vvd", "s2", "Tegen", 30),
        ("factions/vvd", "s3", "Voor", None),  # a roll-call: the member's own
        ("factions/vvd", "s4", "Voor", 30),  # no date: no period holds it
        ("factions/vvd", "s0", "Tegen", 30),
        ("factions/d66", "s1", "Tegen", 9),
        ("factions/d66", "s5", "Voor", 9),  # before the member joined
        ("factions/d66", "s0", "Voor", 9),
        ("members/m1", "s3", "Voor", 1),
        ("members/m1", "s4", "Voor", 1),
        ("members/m1", "s0", "Tegen", 1),
    ):
        g.edge(
            voter, RELATION_VOTED, f"decisions/{decision}", choice=choice, seats=seats
        )
    g.write()


def authorship_graph(store: GraphStore) -> None:
    g = Graph(store)
    vvd = g.node("factions", "vvd", abbreviation="VVD", name="VVD")
    d66 = g.node("factions", "d66", abbreviation="D66", name="D66")
    switcher = g.node(
        "members",
        "m1",
        name="Wisselaar",
        faction_memberships=[
            {"faction_id": vvd, "from_date": "2010-01-01", "to_date": "2019-12-31"},
            {"faction_id": d66, "from_date": "2020-01-01", "to_date": None},
        ],
    )
    loyal = g.node(
        "members",
        "m2",
        name="Trouw",
        faction_memberships=[
            {"faction_id": vvd, "from_date": "2010-01-01", "to_date": None}
        ],
    )
    g.edge(switcher, RELATION_MEMBER_OF, vvd)
    g.edge(switcher, RELATION_MEMBER_OF, d66)
    g.edge(loyal, RELATION_MEMBER_OF, vvd)

    direct = g.node(
        "dossiers",
        "38001",
        number="38001",
        label="38001",
        title="Direct",
        opened_on="2015-01-01",
    )
    through_case = g.node(
        "dossiers",
        "38002",
        number="38002",
        label="38002",
        title="Via een zaak",
        opened_on="2021-01-01",
    )
    untouched = g.node(
        "dossiers",
        "38003",
        number="38003",
        label="38003",
        title="Onaangeroerd",
        opened_on="2022-01-01",
    )
    case = g.node("cases", "zaak1")
    g.edge(case, RELATION_PART_OF, through_case)
    g.edge(g.node("documents", "unrelated"), RELATION_PART_OF, untouched)

    def document(key: str, date: str, parent: str) -> str:
        doc = g.node("documents", key, ["TK"], kind="Motie", date=date)
        g.edge(doc, RELATION_PART_OF, parent)
        return doc

    old_motion = document("old", "2015-06-01", direct)  # signed as VVD
    old_extra = document("old2", "2015-07-01", direct)
    new_motion = document(
        "new", "2021-06-01", case
    )  # signed as D66, dossier through a case
    g.edge(switcher, RELATION_AUTHORED, old_motion, role="Eerste ondertekenaar")
    g.edge(switcher, RELATION_AUTHORED, old_extra, role="Mede ondertekenaar")
    g.edge(switcher, RELATION_AUTHORED, new_motion, role="Eerste ondertekenaar")
    g.edge(loyal, RELATION_AUTHORED, old_extra, role="Mede ondertekenaar")
    g.write()


def signatures(store: GraphStore) -> None:
    """Two members who signed papers and cases of three dossiers (one through a case, one
    gone from the graph), with roles, functions and capacities empty and missing."""
    g = Graph(store)
    g.node("members", "m1", name="Anna")
    g.node(
        "members",
        "m2",
        faction_memberships=[{"faction_id": "factions/vvd", "from_date": "2016-01-01"}],
    )
    g.edge("members/m2", RELATION_MEMBER_OF, "factions/vvd")
    for key, props in (
        ("d1", {"opened_on": "2020-01-01"}),
        ("d2", {"opened_on": "2020-01-01"}),
        ("d3", {}),
    ):
        g.node("dossiers", key, title=key, **props)
    g.node("documents", "doc1", date="2015-06-01")
    g.node("documents", "doc2", date="2021-01-01")
    g.node("documents", "doc3")
    g.node("cases", "k1")
    g.node("cases", "k2", date="2017-01-01")
    g.edge("documents/doc1", RELATION_PART_OF, "dossiers/d1")
    g.edge("documents/doc1", RELATION_PART_OF, "dossiers/gone")
    g.edge("documents/doc2", RELATION_PART_OF, "cases/k1")
    g.edge("cases/k1", RELATION_PART_OF, "dossiers/d1")
    g.edge("cases/k1", RELATION_PART_OF, "dossiers/d2")
    g.edge("documents/doc2", RELATION_PART_OF, "dossiers/d2")
    g.edge("documents/doc3", RELATION_PART_OF, "dossiers/d3")
    g.edge("cases/k2", RELATION_PART_OF, "dossiers/d3")
    signed = (
        ("doc1", {"role": FIRST, "capacity": "bewindspersoon", "function": "minister"}),
        ("doc2", {"role": "", "capacity": "", "function": None}),
        ("doc3", {"role": CO, "capacity": None, "function": "Kamerlid"}),
    )
    for document, meta in signed:
        g.edge("members/m1", RELATION_AUTHORED, f"documents/{document}", **meta)
    g.edge("members/m2", RELATION_AUTHORED, "documents/doc2", role=CO)
    g.edge("members/m2", RELATION_AUTHORED, "documents/doc1", role=FIRST)
    g.edge("members/m2", RELATION_AUTHORED, "cases/k2", role=FIRST)
    g.write()


def candidates_plan(
    store: GraphStore, member_id: str, limit: int, *, in_office: bool = False
) -> list[dict[str, Any]]:
    """The nodes of the plan (EXPLAIN ANALYZE) of the candidates of the votes of a member,
    as ``get_member_votes`` reads them first."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        calls = recorded(store, monkeypatch)
        votes = get_member_votes(store, member_id, limit=limit, in_office=in_office)
        assert len(votes) == limit
    statement, params, *_ = [c for c in calls if c.params and "candidates" in c.params][
        0
    ]
    plan = explain(store, statement, params, analyze=True)
    (candidates,) = [
        n for n in plan_nodes(plan) if n.get("Subplan Name") == "CTE candidates"
    ]
    return list(plan_nodes(candidates))


def decisions_voted(
    store: GraphStore,
    memberships: list[dict[str, Any]],
    posts: list[dict[str, Any]] | None = None,
) -> None:
    """A member of *memberships* (in the government during *posts*) and 3,000 decisions
    of 2020-2025 the factions of those all voted on."""
    g = Graph(store)
    g.node(
        "members",
        "m1",
        name="Anna",
        party="D66",
        faction_memberships=memberships,
        government_functions=posts or [],
    )
    factions = sorted({m["faction_id"] for m in memberships})
    for faction in factions:
        g.node("factions", faction.split("/")[1], name=faction)
    for n in range(3000):
        key = f"s{n:04d}"
        g.node(
            "decisions", key, date=f"{2020 + n % 6}-{1 + n % 12:02d}-{1 + n % 28:02d}"
        )
        for faction in factions:
            g.edge(faction, RELATION_VOTED, f"decisions/{key}", choice="Voor")
    g.write()
    store.vacuum_analyze()
