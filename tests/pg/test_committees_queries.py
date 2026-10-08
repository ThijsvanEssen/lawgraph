"""The committee, member and faction queries on a real PostgreSQL: the committees with their
members, dossiers and activities, the member and faction lists, the seats on a day, a
member's votes, the laws an actor changes, the dossiers an actor authored in and the votes of
a faction of the Eerste Kamer; and the routes in front of them."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.api.routes import committees as committee_routes
from lawgraph.config.constants import (
    COLLECTION_DECISIONS,
    COLLECTION_EDGES,
    COLLECTION_MEMBERS,
    RELATION_ABOUT,
    RELATION_AMENDS,
    RELATION_AUTHORED,
    RELATION_INTRODUCES,
    RELATION_LED_BY,
    RELATION_MEMBER_OF,
    RELATION_PART_OF,
    RELATION_REPEALS,
    RELATION_VOTED,
)
from lawgraph.core.models import Node, NodeType
from lawgraph.core.tk_records import VOTE_KIND_MEMBER
from lawgraph.db import GraphStore, NodeWriter, make_edge_doc
from lawgraph.db.queries import committees as committee_queries
from lawgraph.db.queries.committees import (
    _IN_MEMBERSHIP,
    _array,
    _is_null,
    get_actor_dossiers,
    get_actor_touched_instruments,
    get_committee_activities,
    get_committee_detail,
    get_committees,
    get_ek_faction_votes,
    get_ek_members,
    get_factions,
    get_member_committees,
    get_member_votes,
    get_members,
    get_seats_on,
)

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


def _keys(docs: list[dict[str, Any]]) -> list[str]:
    return [doc["_key"] for doc in docs]


@pytest.fixture()
def client(store: GraphStore) -> Iterator[TestClient]:
    committee_routes._faction_dossiers_cache.clear()
    app.dependency_overrides[get_store] = lambda: store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_store, None)
        committee_routes._faction_dossiers_cache.clear()


# ── committees ───────────────────────────────────────────────────────────────


def test_the_committees_of_a_chamber_with_a_name_by_name_then_key(
    store: GraphStore,
) -> None:
    g = Graph(store)
    g.node("committees", "c_b", name="Commissie B", slug="b")
    g.node("committees", "c_a2", name="Commissie A", slug="a2")
    g.node("committees", "c_a", name="Commissie A", slug="a")
    g.node("committees", "c_empty", name="")
    g.node("committees", "c_none")
    # a name that is just a GUID, in either case
    g.node("committees", "c_guid", name="0F8FAD5B-D9CB-469F-A165-70867728950E")
    g.node("committees", "c_guid2", name="0f8fad5b-d9cb-469f-a165-70867728950e")
    g.node("committees", "c_old", name="Gestopt", observed_until="2023-01-01")
    g.node("committees", "c_tk", name="Expliciet", chamber="TK")
    g.node("committees", "ek_fin", name="Financiën", chamber="EK")
    g.node("committees", "ek_old", name="Oud", chamber="EK", observed_until="2024")
    g.write()

    tk = get_committees(store)
    assert _keys(tk) == ["c_a", "c_a2", "c_b", "c_tk"]
    assert list(tk[0]) == ["_key", "_id", "type", "labels", "props"]
    assert tk[0]["_id"] == "committees/c_a"
    assert _keys(get_committees(store, chamber="EK")) == ["ek_fin"]


def _committee_graph(store: GraphStore) -> None:
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


def test_a_committee_by_slug_or_key_the_key_settling_a_slug_that_is_a_key(
    store: GraphStore,
) -> None:
    _committee_graph(store)
    for slug in ("b", "B", "c_b", "C_B"):
        found = get_committee_detail(store, slug)
        assert found is not None and found["_key"] == "c_b"
    # ``x`` is the slug of ``zz`` and the key of ``x``: the lower key wins
    found = get_committee_detail(store, "x")
    assert found is not None and found["_key"] == "x"
    assert get_committee_detail(store, "nope") is None
    assert get_committee_activities(store, "nope") is None


def test_the_members_of_a_committee_by_name_then_key_with_their_seat(
    store: GraphStore,
) -> None:
    _committee_graph(store)
    current = get_committee_detail(store, "b")
    assert current is not None
    # no name first; an end date ahead, none or not a date; the past and the unobserved
    # seats are left out
    assert _keys(current["members"]) == ["m3", "m1", "Zz", "m5"]
    seat = current["members"][3]
    assert list(seat)[5:] == [
        "from_date",
        "to_date",
        "role",
        "observed_from",
        "observed_until",
    ]
    assert (seat["from_date"], seat["to_date"], seat["role"]) == (
        "2020-01-01",
        "2999-01-01",
        "voorzitter",
    )
    assert seat["observed_from"] == "2020-02-01" and seat["observed_until"] is None

    every = get_committee_detail(store, "b", current_only=False)
    assert every is not None
    assert _keys(every["members"]) == ["m3", "m1", "m2", "Zz", "m4", "m5", "m6"]
    assert list(every)[-3:] == ["members", "dossiers", "dossier_total"]


def test_the_dossiers_of_a_committee_newest_opened_first_by_status_and_paged(
    store: GraphStore,
) -> None:
    _committee_graph(store)
    detail = get_committee_detail(store, "b")
    assert detail is not None
    # the same opening day settled by key, the undated last; a dossier that is gone is not
    # counted
    assert _keys(detail["dossiers"]) == ["d1", "d2", "d4", "d5", "d3"]
    assert detail["dossier_total"] == 5 and isinstance(detail["dossier_total"], int)

    closed = get_committee_detail(store, "b", status="closed")
    assert closed is not None
    assert _keys(closed["dossiers"]) == ["d4"] and closed["dossier_total"] == 1
    # ``"true"`` is no closed dossier
    opened = get_committee_detail(store, "b", status="open")
    assert opened is not None
    assert _keys(opened["dossiers"]) == ["d1", "d2", "d5", "d3"]

    page = get_committee_detail(store, "b", limit=2, offset=1)
    assert page is not None and _keys(page["dossiers"]) == ["d2", "d4"]
    past = get_committee_detail(store, "b", limit=2, offset=10)
    assert past is not None
    assert past["dossiers"] == [] and past["dossier_total"] == 5


def test_the_activities_of_a_committee_newest_first_with_their_fields(
    store: GraphStore,
) -> None:
    _committee_graph(store)
    page = get_committee_activities(store, "b")
    assert page is not None
    assert list(page) == ["total", "items"] and page["total"] == 5
    assert [row["key"] for row in page["items"]] == ["a1", "a2", "a5", "a6", "a3"]
    assert json.dumps(page["items"][0]) == json.dumps(
        {
            "id": "activities/a1",
            "key": "a1",
            "date": "2024-01-01",
            "kind": "Debat",
            "agenda_title": None,
            "status": None,
            "dossier_numbers": ["36000"],
        }
    )
    # ``dossier_numbers OR []``: an empty list stays, "" and a missing one are [], an
    # object is true
    numbers = {row["key"]: row["dossier_numbers"] for row in page["items"]}
    assert numbers == {"a1": ["36000"], "a2": [], "a5": [], "a6": {}, "a3": []}

    tail = get_committee_activities(store, "b", limit=2, offset=4)
    assert tail is not None and [row["key"] for row in tail["items"]] == ["a3"]
    past = get_committee_activities(store, "b", limit=2, offset=50)
    assert past == {"total": 5, "items": []}
    empty = get_committee_activities(store, "x")
    assert empty == {"total": 0, "items": []}


def test_the_committee_pages_dossiers_by_status_and_lists_its_activities(
    store: GraphStore,
) -> None:
    g = Graph(store)
    committee = g.node("committees", "c_a", name="Commissie A", slug="a")
    other = g.node("committees", "c_b", name="Commissie B", slug="b")
    for number in range(5):
        closed = number >= 3
        dossier = g.node(
            "dossiers",
            f"3700{number}",
            number=f"3700{number}",
            label=f"3700{number}",
            closed=closed,
            opened_on=f"2024-0{number + 1}-01",
        )
        activity = g.node(
            "activities",
            f"a{number}",
            date=f"2024-0{number + 1}-10",
            kind="Commissiedebat",
            agenda_title=f"Debat {number}",
            dossier_numbers=[f"3700{number}"],
        )
        g.edge(activity, RELATION_ABOUT, dossier)
        g.edge(activity, RELATION_LED_BY, committee)
    stray = g.node("activities", "stray", date="2025-01-01", kind="Hoorzitting")
    g.edge(stray, RELATION_LED_BY, other)
    g.write()

    everything = get_committee_detail(store, "a", limit=2)
    assert everything is not None
    # the open ones are counted once, by ``semantic graph-list-stats`` (test_committees)
    assert everything["dossier_total"] == 5
    assert [d["_key"] for d in everything["dossiers"]] == [
        "37004",
        "37003",
    ]  # newest opened

    second = get_committee_detail(store, "A", limit=2, offset=2)
    assert second is not None
    assert [d["_key"] for d in second["dossiers"]] == ["37002", "37001"]

    closed = get_committee_detail(store, "a", status="closed")
    assert closed is not None
    assert closed["dossier_total"] == 2
    assert {d["_key"] for d in closed["dossiers"]} == {"37003", "37004"}

    opened = get_committee_detail(store, "a", status="open")
    assert opened is not None
    assert opened["dossier_total"] == 3
    assert {d["_key"] for d in opened["dossiers"]} == {"37000", "37001", "37002"}

    assert get_committee_detail(store, "nope") is None

    page = get_committee_activities(store, "a", limit=2)
    assert page is not None and page["total"] == 5
    assert [row["key"] for row in page["items"]] == ["a4", "a3"]  # newest first
    assert page["items"][0] == {
        "id": "activities/a4",
        "key": "a4",
        "date": "2024-05-10",
        "kind": "Commissiedebat",
        "agenda_title": "Debat 4",
        "status": None,
        "dossier_numbers": ["37004"],
    }
    rest = get_committee_activities(store, "a", limit=2, offset=4)
    assert rest is not None and [row["key"] for row in rest["items"]] == ["a0"]
    assert get_committee_activities(store, "nope") is None


# ── members and factions ─────────────────────────────────────────────────────

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


def _people(store: GraphStore) -> None:
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


def test_members_who_held_a_seat_by_name_then_key(store: GraphStore) -> None:
    _people(store)
    assert _keys(get_members(store)) == ["m1", "m2", "Zz", "m3", "m6"]
    everyone = get_members(store, include_all=True)
    assert _keys(everyone) == ["m1", "m2", "Zz", "m3", "m4", "m6", "m9", "m7"]
    assert list(everyone[0]) == ["_key", "_id", "type", "labels", "props"]
    assert _keys(get_members(store, government=True)) == ["m4", "m7"]
    assert _keys(get_members(store, cabinet="cab1")) == ["m4", "m7"]
    assert _keys(get_members(store, cabinet="cab2")) == ["m7"]
    page = get_members(store, include_all=True, limit=3, offset=2)
    assert _keys(page) == ["Zz", "m3", "m4"]
    assert get_members(store, include_all=True, offset=100) == []


def test_members_by_surname_then_tussenvoegsel(store: GraphStore) -> None:
    g = Graph(store)
    seat = [{**VVD, "to_date": None}]
    g.node(
        "members",
        "a",
        name="Ard van der Steur",
        family_name="Steur",
        name_prefix="van der",
        faction_memberships=seat,
    )
    g.node(
        "members", "b", name="Bas Steur", family_name="Steur", faction_memberships=seat
    )
    g.node(
        "members",
        "c",
        name="Cees de Aa",
        family_name="Aa",
        name_prefix="de",
        faction_memberships=seat,
    )
    g.node(
        "members",
        "d",
        name="Dirk Yeşilgöz",
        family_name="Yeşilgöz",
        faction_memberships=seat,
    )
    # a name without its parts (a member the Kamer names by roll calls only): last
    g.node("members", "e", name="Anna", faction_memberships=seat)
    g.write()
    assert _keys(get_members(store)) == ["e", "a", "b", "c", "d"]
    by_surname = get_members(store, sort="family_name")
    assert _keys(by_surname) == ["c", "b", "a", "d", "e"]
    assert _keys(get_members(store, sort="family_name", limit=2, offset=1)) == [
        "b",
        "a",
    ]


def test_members_by_party_name_and_seat(store: GraphStore) -> None:
    _people(store)
    # the party, or an abbreviation, name or alias in the timeline, in any case
    assert _keys(get_members(store, party=" vvd ")) == ["m1", "m2", "Zz", "m3"]
    assert _keys(get_members(store, party="volkspartij")) == ["m1", "m2", "Zz", "m3"]
    assert _keys(get_members(store, party="democraten 66")) == ["m1", "m6"]
    assert get_members(store, party="cda") == []
    # seated: a membership without an end
    assert _keys(get_members(store, active=True)) == ["m1", "m2", "Zz", "m6"]
    assert _keys(get_members(store, active=False)) == ["m3"]
    # a name part, in any case, also beyond ASCII; nothing contains ""
    assert _keys(get_members(store, q="ann")) == ["m1", "m2", "Zz"]
    assert _keys(get_members(store, q="émile", include_all=True)) == ["m6", "m9"]
    assert get_members(store, q="  ") == []


def test_the_members_of_the_eerste_kamer(store: GraphStore) -> None:
    _people(store)
    # one without a name comes first
    assert _keys(get_ek_members(store)) == ["m8", "m6", "m7"]
    assert _keys(get_ek_members(store, active=True)) == ["m8", "m6"]
    assert _keys(get_ek_members(store, active=False)) == ["m7"]
    assert _keys(get_ek_members(store, party="VVD")) == ["m8", "m6"]
    assert _keys(get_ek_members(store, q="émile e")) == ["m6"]
    assert _keys(get_ek_members(store, q="zo")) == ["m7"]
    assert get_ek_members(store, q=" ") == []
    assert _keys(get_ek_members(store, limit=1, offset=1)) == ["m6"]


def _plan(store: GraphStore, call: Any) -> str:
    """The plan PostgreSQL makes for the one statement *call* runs on *store*."""
    seen: list[tuple[Any, Any]] = []
    query = store.query

    def spy(statement: Any, params: Any = None, **kw: Any) -> Any:
        seen.append((statement, params))
        return query(statement, params, **kw)

    store.query = spy  # type: ignore[method-assign]
    try:
        call()
    finally:
        store.query = query  # type: ignore[method-assign]
    [(statement, params)] = seen
    with store.pool.connection() as conn:
        conn.execute(b"ANALYZE members")
        rows = conn.execute(("EXPLAIN " + statement).encode(), params).fetchall()
    return "\n".join(row[0] for row in rows)


def test_a_page_of_members_is_read_from_an_index_in_name_order(
    store: GraphStore,
) -> None:
    """The lists filter and sort on columns (``list_name``, ``in_parliament``, ``in_ek``):
    a page is read from a partial index in name order, not from every member's props."""
    _people(store)
    g = Graph(store)
    for n in range(3000):  # people who never held a seat: what the TK lists most
        g.node("members", f"filler{n:04d}", name=f"Iemand {n}")
    g.write()
    tk = _plan(store, lambda: get_members(store, limit=5))
    assert "members_list_name" in tk and "Seq Scan" not in tk
    ek = _plan(store, lambda: get_ek_members(store, limit=5))
    assert "members_list_ek" in ek and "Seq Scan" not in ek
    assert _keys(get_members(store, limit=2)) == ["m1", "m2"]


def _factions(store: GraphStore) -> None:
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
    for member in ("m1", "m2", "m3"):
        g.node("members", member, name=member)
    g.edge("members/m1", RELATION_MEMBER_OF, "factions/vvd")
    g.edge("members/m2", RELATION_MEMBER_OF, "factions/vvd", observed_until=None)
    g.edge("members/m3", RELATION_MEMBER_OF, "factions/vvd", observed_until="2020")
    g.edge("members/m3", RELATION_MEMBER_OF, "factions/ek_vvd", chamber="EK")
    g.edge("members/m1", RELATION_MEMBER_OF, "factions/d66")
    g.write()


def test_factions_seated_first_by_abbreviation_name_and_key_with_their_members(
    store: GraphStore,
) -> None:
    _factions(store)
    factions = get_factions(store)
    # seated, then not, then unknown; no abbreviation before one; a name settles one
    assert _keys(factions) == ["d66", "z", "vvd", "cda", "none"]
    counts = {doc["_key"]: doc["member_count"] for doc in factions}
    assert counts == {"d66": 1, "z": 0, "vvd": 2, "cda": 0, "none": 0}
    assert all(type(count) is int for count in counts.values())
    assert list(factions[0]) == [
        "_key",
        "_id",
        "type",
        "labels",
        "props",
        "member_count",
    ]
    assert _keys(get_factions(store, active=True)) == ["d66", "z", "vvd"]
    assert _keys(get_factions(store, active=False)) == ["cda"]
    assert _keys(get_factions(store, q="d6")) == ["d66", "z"]
    assert _keys(get_factions(store, q="ZET")) == ["z"]
    assert get_factions(store, q="  ") == []
    ek = get_factions(store, chamber="EK")
    assert _keys(ek) == ["ek_vvd"] and ek[0]["member_count"] == 1


def test_the_seats_of_each_faction_on_a_day(store: GraphStore) -> None:
    g = Graph(store)
    g.node("members", "m1", faction_memberships=[VVD, D66])
    g.node("members", "m2", faction_memberships=[{**VVD, "to_date": None}])
    # twice in one faction on the day: one seat
    g.node("members", "m3", faction_memberships=[VVD, {**VVD, "to_date": None}])
    g.node("members", "m4", faction_memberships=[{**D66, "from_date": None}])
    g.node("members", "m5", faction_memberships="none")
    g.write()
    assert get_seats_on(store, "2015-01-01") == {"vvd": 3}
    assert get_seats_on(store, "2019-12-31") == {"vvd": 3}
    assert get_seats_on(store, "2024-01-01") == {"d66": 1, "vvd": 2}
    assert list(get_seats_on(store, "2024-01-01")) == ["d66", "vvd"]
    assert get_seats_on(store, "2000-01-01") == {}


# ── votes ────────────────────────────────────────────────────────────────────


def _votes(store: GraphStore) -> None:
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


def test_a_member_votes_by_roll_call_and_through_the_factions_of_the_day(
    store: GraphStore,
) -> None:
    _votes(store)
    votes = get_member_votes(store, "members/m1")
    # newest first; one day settled by key, then the member's own vote before the
    # faction's; the undated last
    assert [(v["decision_key"], v["faction_key"], v["vote_source"]) for v in votes] == [
        ("s0", None, "member"),
        ("s0", "d66", "faction"),
        ("s1", "d66", "faction"),
        ("s3", None, "member"),
        ("s2", "vvd", "faction"),
        ("s4", None, "member"),
    ]
    assert json.dumps(votes[1]) == json.dumps(
        {
            "decision_id": "decisions/s0",
            "decision_key": "s0",
            "external_id": None,
            "date": "2024-01-01",
            "subject": None,
            "passed": True,
            "choice": "Voor",
            "seats": 9,
            "party": "D66",
            "faction_key": "d66",
            "vote_source": "faction",
        }
    )
    # their own vote carries the party they sit for now; a faction's that of the day
    assert votes[0]["party"] == "D66" and votes[4]["party"] == "VVD"
    assert votes[2]["external_id"] == "b1" and type(votes[2]["seats"]) is int
    assert len(get_member_votes(store, "members/m1", limit=2)) == 2
    assert get_member_votes(store, "members/nobody") == []


# The statement of ``get_member_votes`` before it read the newest votes of a period first:
# what it answers must not change.
_OLD_MEMBER_VOTES = f"""
        WITH member AS (
            SELECT props FROM {COLLECTION_MEMBERS} WHERE id = %(member_id)s
        ),
        voted AS (
            SELECT e.to_id AS decision_id, e.doc -> 'meta' AS meta,
                   member.props -> 'party' AS party,
                   NULL::json AS faction_key, NULL::text AS faction_order,
                   'member'::text AS vote_source
            FROM member
            JOIN {COLLECTION_EDGES} e
              ON e.from_id = %(member_id)s AND e.relation = %(voted)s
            UNION ALL
            SELECT e.to_id, e.doc -> 'meta',
                   CASE WHEN {_is_null("f.period -> 'abbreviation'")}
                        THEN f.period -> 'name' ELSE f.period -> 'abbreviation' END,
                   f.period -> 'faction_key', f.period ->> 'faction_key',
                   'faction'::text
            FROM member
            CROSS JOIN LATERAL json_array_elements(
                {_array("member.props -> 'faction_memberships'")}
            ) AS f(period)
            JOIN {COLLECTION_EDGES} e
              ON e.from_id = f.period ->> 'faction_id' AND e.relation = %(voted)s
            JOIN {COLLECTION_DECISIONS} d ON d.id = e.to_id
            WHERE d.date IS NOT NULL
              AND lg_str(d.props -> 'vote_kind') IS DISTINCT FROM %(roll_call)s
              AND {_IN_MEMBERSHIP}
        ),
        page AS (
            SELECT v.*, d.key, d.date
            FROM voted v JOIN {COLLECTION_DECISIONS} d ON d.id = v.decision_id
            ORDER BY d.date DESC NULLS LAST, d.key ASC, v.faction_order ASC NULLS FIRST
            LIMIT %(limit)s
        )
        SELECT json_build_object(
            'decision_id', d.id,
            'decision_key', d.key,
            'external_id', d.props -> 'decision_id',
            'date', d.props -> 'date',
            'subject', d.props -> 'subject',
            'passed', d.props -> 'passed',
            'choice', page.meta -> 'choice',
            'seats', page.meta -> 'seats',
            'party', page.party,
            'faction_key', page.faction_key,
            'vote_source', page.vote_source
        )
        FROM page JOIN {COLLECTION_DECISIONS} d ON d.id = page.decision_id
        ORDER BY page.date DESC NULLS LAST, page.key ASC,
                 page.faction_order ASC NULLS FIRST
        """


def _old_member_votes(store: GraphStore, member_id: str, limit: int) -> list[Any]:
    return list(
        store.query(
            _OLD_MEMBER_VOTES,
            {
                "member_id": member_id,
                "limit": limit,
                "voted": RELATION_VOTED,
                "roll_call": VOTE_KIND_MEMBER,
            },
        )
    )


def _roll_call(n: int) -> bool:
    return n % 5 == 0 or n % 12 == 11  # the year 2023: the newest votes all roll-calls


def _many_votes(store: GraphStore) -> None:
    """Two factions of a member, 300 decisions over twelve years, one in five a roll-call
    (the member's own vote) and every one of the last year (the member absent: no vote of
    their own), some on one day."""
    g = Graph(store)
    g.node("members", "m1", name="Anna", party="D66", faction_memberships=[VVD, D66])
    g.node("factions", "vvd", name="VVD")
    g.node("factions", "d66", name="D66")
    for n in range(300):
        date = f"{2012 + n % 12}-{1 + n % 12:02d}-{1 + (n // 12) % 28:02d}"
        roll_call = _roll_call(n)
        key = f"s{n:03d}"
        g.node(
            "decisions",
            key,
            date=date,
            **({"vote_kind": VOTE_KIND_MEMBER} if roll_call else {}),
        )
        for faction in ("factions/vvd", "factions/d66"):
            g.edge(faction, RELATION_VOTED, f"decisions/{key}", choice="Voor", seats=9)
        if roll_call and n % 12 != 11:
            g.edge("members/m1", RELATION_VOTED, f"decisions/{key}", choice="Tegen")
    g.write()


@pytest.mark.parametrize("candidates", [committee_queries.VOTE_CANDIDATES, 1])
def test_the_newest_votes_are_those_of_every_vote(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch, candidates: int
) -> None:
    """The votes of a faction read newest first, before the roll-calls among them are
    known, answer what reading every vote answered; with too few read (a page of
    roll-calls) the statement reads more."""
    _many_votes(store)
    monkeypatch.setattr(committee_queries, "VOTE_CANDIDATES", candidates)
    for limit in (1, 7, 50, 100):
        new = get_member_votes(store, "members/m1", limit=limit)
        assert new == _old_member_votes(store, "members/m1", limit), limit
        assert len(new) == limit
    # the roll-calls are the member's own, never the faction's
    votes = get_member_votes(store, "members/m1", limit=300)
    assert not [
        v
        for v in votes
        if v["vote_source"] == "faction" and _roll_call(int(v["decision_key"][1:]))
    ]
    assert len([v for v in votes if v["vote_source"] == "member"]) == len(
        [n for n in range(300) if _roll_call(n) and n % 12 != 11]
    )


def test_a_faction_of_the_eerste_kamer_its_votes_counts_and_items(
    store: GraphStore,
) -> None:
    g = Graph(store)
    decisions = {
        "e1": {
            "date": "2024-02-01",
            "factions_for": ["VVD", "D66"],
            "factions_against": ["GL-PvdA"],
            "dossier_numbers": ["36000"],
            "result": "Aangenomen",
            "method": "zonder stemming",
            "bill_decision": True,
            "subject": "Wet",
        },
        "e2": {"date": "2024-02-01", "factions_against": ["VVD"]},
        "e3": {"factions_noted": ["VVD"]},
        "e4": {"date": "2023-01-01", "factions_for": "VVD"},
        "e6": {
            "date": "2022-01-01",
            "factions_for": ["VVD"],
            "factions_against": ["VVD"],
            "dossier_numbers": [],
        },
        "e8": {"date": "2020-01-01", "factions_against": ["vvd"]},
    }
    for key, props in decisions.items():
        g.node("decisions", key, ["EK"], chamber="EK", **props)
    g.node("decisions", "t1", ["TK"], chamber="TK", factions_for=["VVD"])
    g.write()

    votes = get_ek_faction_votes(store, "VVD")
    assert list(votes) == ["total", "counts", "items"] and votes["total"] == 4
    # the choices in their order
    assert json.dumps(votes["counts"]) == json.dumps(
        {"aantekening gevraagd": 1, "tegen": 1, "voor": 2}
    )
    assert [(i["decision_key"], i["choice"]) for i in votes["items"]] == [
        ("e1", "voor"),
        ("e2", "tegen"),
        ("e6", "voor"),
        ("e3", "aantekening gevraagd"),
    ]
    assert json.dumps(votes["items"][0]) == json.dumps(
        {
            "decision_id": "decisions/e1",
            "decision_key": "e1",
            "date": "2024-02-01",
            "subject": "Wet",
            "dossier_numbers": ["36000"],
            "result": "Aangenomen",
            "method": "zonder stemming",
            "bill_decision": True,
            "choice": "voor",
        }
    )
    assert votes["items"][3]["dossier_numbers"] == []
    # an undated vote is before every day
    to = get_ek_faction_votes(store, "VVD", date_to="2023-12-31")
    assert [i["decision_key"] for i in to["items"]] == ["e6", "e3"]
    since = get_ek_faction_votes(store, "VVD", date_from="2022-01-01")
    assert [i["decision_key"] for i in since["items"]] == ["e1", "e2", "e6"]
    page = get_ek_faction_votes(store, "VVD", limit=2, offset=2)
    assert page["total"] == 4 and [i["decision_key"] for i in page["items"]] == [
        "e6",
        "e3",
    ]
    assert get_ek_faction_votes(store, "VVD", offset=10)["items"] == []
    assert get_ek_faction_votes(store, "nope") == {
        "total": 0,
        "counts": {},
        "items": [],
    }


# ── what an actor authored ───────────────────────────────────────────────────


def test_the_laws_an_actor_changes_most_by_documents_then_id(
    store: GraphStore,
) -> None:
    g = Graph(store)
    g.node("instruments", "i1", display_name="Wet 1", bwb_id="BWBR1", title="Een")
    g.node("instruments", "i2", display_name="Wet 2", celex="3201")
    for document in ("doc1", "doc2", "doc3"):
        g.edge("members/m1", RELATION_AUTHORED, f"documents/{document}")
    g.edge("documents/doc1", RELATION_AMENDS, "articles/a1")
    g.edge("documents/doc1", RELATION_INTRODUCES, "articles/a2")
    g.edge("documents/doc2", RELATION_AMENDS, "articles/a1")
    g.edge("documents/doc3", RELATION_REPEALS, "articles/a3")
    g.edge("documents/doc3", RELATION_AMENDS, "articles/a4")
    g.edge("documents/doc3", RELATION_PART_OF, "articles/a1")  # not a change
    g.edge("articles/a1", RELATION_PART_OF, "instruments/i2")
    g.edge("articles/a2", RELATION_PART_OF, "instruments/i1")
    g.edge("articles/a3", RELATION_PART_OF, "instruments/i1")
    g.edge("articles/a4", RELATION_PART_OF, "instruments/gone")
    g.write()

    laws = get_actor_touched_instruments(store, "members/m1")
    assert [(law["id"], law["count"]) for law in laws] == [
        ("instruments/i1", 2),
        ("instruments/i2", 2),
    ]
    assert json.dumps(laws[0]) == json.dumps(
        {
            "id": "instruments/i1",
            "key": "i1",
            "display_name": "Wet 1",
            "title": "Een",
            "short_title": None,
            "citation_title": None,
            "bwb_id": "BWBR1",
            "celex": None,
            "count": 2,
        }
    )
    assert [
        law["key"]
        for law in get_actor_touched_instruments(store, "members/m1", limit=1)
    ] == ["i1"]
    # the limit is taken before a law that is gone is left out
    g.edge("documents/doc1", RELATION_AMENDS, "articles/a4")
    g.edge("documents/doc2", RELATION_AMENDS, "articles/a4")
    g.write()
    assert [
        law["key"]
        for law in get_actor_touched_instruments(store, "members/m1", limit=1)
    ] == []
    assert get_actor_touched_instruments(store, "members/none") == []


def _authorship_graph(store: GraphStore) -> None:
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


def test_a_member_and_a_faction_list_the_dossiers_they_authored_in(
    store: GraphStore,
) -> None:
    _authorship_graph(store)

    member = get_actor_dossiers(store, "members/m1")
    assert member["total"] == 2
    first, second = member["items"]  # newest opened first
    assert first["dossier"]["_key"] == "38002"
    assert first["roles"] == ["Eerste ondertekenaar"] and first["document_count"] == 1
    assert second["dossier"]["_key"] == "38001"
    assert second["roles"] == ["Eerste ondertekenaar", "Mede ondertekenaar"]
    assert second["document_count"] == 2

    page = get_actor_dossiers(store, "members/m1", limit=1, offset=1)
    assert page["total"] == 2 and [r["dossier"]["_key"] for r in page["items"]] == [
        "38001"
    ]

    # A faction counts what its members signed while they belonged to it.
    vvd = get_actor_dossiers(store, "factions/vvd")
    assert vvd["total"] == 1
    assert vvd["items"][0]["dossier"]["_key"] == "38001"
    assert vvd["items"][0]["document_count"] == 2  # both old motions, by two members
    assert vvd["items"][0]["roles"] == ["Eerste ondertekenaar", "Mede ondertekenaar"]

    d66 = get_actor_dossiers(store, "factions/d66")
    assert d66["total"] == 1 and d66["items"][0]["dossier"]["_key"] == "38002"

    assert get_actor_dossiers(store, "members/nobody") == {"total": 0, "items": []}


def test_the_dossiers_of_an_actor_carry_distinct_roles_functions_and_capacities(
    store: GraphStore,
) -> None:
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

    result = get_actor_dossiers(store, "members/m1")
    assert list(result) == ["total", "items"] and result["total"] == 3
    # one opening day settled by key, the undated last
    assert [row["dossier"]["_key"] for row in result["items"]] == ["d1", "d2", "d3"]
    d1 = result["items"][0]
    assert list(d1) == ["dossier", "roles", "functions", "capacities", "document_count"]
    # "" is no role or function, but a capacity
    assert d1["roles"] == [FIRST]
    assert d1["functions"] == ["minister"]
    assert d1["capacities"] == ["", "bewindspersoon"]
    assert d1["document_count"] == 2 and type(d1["document_count"]) is int
    assert result["items"][2]["capacities"] == []

    # a faction: on the day of the document or case, from the member's start
    vvd = get_actor_dossiers(store, "factions/vvd")
    assert [row["dossier"]["_key"] for row in vvd["items"]] == ["d1", "d2", "d3"]
    assert vvd["items"][0]["roles"] == [CO]
    assert get_actor_dossiers(store, "members/m1", offset=10) == {
        "total": 3,
        "items": [],
    }


def test_a_big_faction_and_a_busy_committee_answer_in_one_query_each(
    store: GraphStore,
) -> None:
    """60 members who each signed 250 motions in 50 dossiers, and 3,000 debates."""
    g = Graph(store)
    faction = g.node("factions", "vvd", abbreviation="VVD")
    committee = g.node("committees", "c_a", name="Commissie A", slug="a")
    dossiers = [
        g.node(
            "dossiers",
            f"39{n:03d}",
            number=f"39{n:03d}",
            label=f"39{n:03d}",
            opened_on="2024-01-01",
        )
        for n in range(50)
    ]
    for member in range(60):
        person = g.node(
            "members",
            f"m{member}",
            faction_memberships=[
                {"faction_id": faction, "from_date": "2000-01-01", "to_date": None}
            ],
        )
        g.edge(person, RELATION_MEMBER_OF, faction)
        for number in range(250):
            document = g.node(
                "documents",
                f"m{member}_d{number}",
                ["TK"],
                kind="Motie",
                date="2024-01-01",
            )
            g.edge(document, RELATION_PART_OF, dossiers[number % 50])
            g.edge(person, RELATION_AUTHORED, document, role="Eerste ondertekenaar")
    for number in range(3000):
        activity = g.node(
            "activities",
            f"act{number}",
            date=f"2024-01-{number % 28 + 1:02d}",
            kind="Debat",
        )
        g.edge(activity, RELATION_LED_BY, committee)
    g.write()

    started = time.monotonic()
    result = get_actor_dossiers(store, faction, limit=10)
    faction_seconds = time.monotonic() - started
    started = time.monotonic()
    page = get_committee_activities(store, "a", limit=10, offset=100)
    committee_seconds = time.monotonic() - started

    assert result["total"] == 50 and len(result["items"]) == 10
    assert (
        result["items"][0]["document_count"] == 300
    )  # 15,000 documents over 50 dossiers
    assert page is not None and page["total"] == 3000 and len(page["items"]) == 10
    assert faction_seconds < 5.0 and committee_seconds < 2.0, (
        faction_seconds,
        committee_seconds,
    )


# ── the routes ───────────────────────────────────────────────────────────────


def test_the_routes_answer_from_the_real_graph(
    store: GraphStore, client: TestClient
) -> None:
    g = Graph(store)
    lead = g.node("committees", "c_a", name="Commissie A", slug="a")
    dossier = g.node("dossiers", "36001", number="36001", label="36001", closed=False)
    case = g.node("cases", "case1", title="Zaak")
    g.edge(case, RELATION_PART_OF, dossier)
    for key, about, date in (
        ("act1", dossier, "2024-06-01"),
        ("act5", case, "2024-06-02"),
    ):
        activity = g.node("activities", key, date=date, kind="Commissiedebat")
        g.edge(activity, RELATION_ABOUT, about)
        g.edge(activity, RELATION_LED_BY, lead)
    g.edge("activities/act5", RELATION_ABOUT, dossier)
    g.write()
    _authorship_graph(store)

    activities = client.get("/api/committees/a/activities?limit=1").json()
    assert activities["total"] == 2 and activities["items"][0]["key"] == "act5"
    assert client.get("/api/committees/a?status=open").json()["dossier_total"] == 1
    assert [c["slug"] for c in client.get("/api/committees").json()] == ["a"]

    member = client.get("/api/members/m1/dossiers").json()
    assert member["actor_id"] == "members/m1" and member["total"] == 2
    assert member["items"][0]["number"] == "38002"
    faction = client.get("/api/factions/vvd/dossiers").json()
    assert faction["total"] == 1 and faction["items"][0]["document_count"] == 2
    assert [f["key"] for f in client.get("/api/factions").json()] == ["d66", "vvd"]


def test_walking_the_pages_of_the_members_finds_every_row_once(
    store: GraphStore, client: TestClient
) -> None:
    """Moved from ``tests/integration/test_stable_paging.py``: 60 members of one name."""
    rows = 60
    with NodeWriter(store) as writer:
        writer.add_all(
            Node(
                collection="members",
                type=NodeType.MEMBER,
                key=f"member_{i:03d}",
                labels=["TK"],
                props={"name": "Jansen"},
            )
            for i in range(rows)
        )
    seen: list[Any] = []
    for offset in range(0, rows, 7):
        body = client.get(
            f"/api/members?include_all=true&limit=7&offset={offset}"
        ).json()
        seen += [row["key"] for row in body]
    assert seen == [f"member_{i:03d}" for i in range(rows)]


def test_the_committees_of_a_member_with_their_seat_and_role(
    store: GraphStore,
) -> None:
    g = Graph(store)
    member = g.node("members", "m1", name="Anna")
    jv = g.node("committees", "jv", name="Justitie en Veiligheid", slug="jv")
    fin = g.node("committees", "fin", name="Financiën", slug="fin", abbreviation="FIN")
    ek = g.node("committees", "ek_fin", name="Financiën", slug="ek-fin", chamber="EK")
    g.edge(
        member,
        "MEMBER_OF",
        jv,
        from_date="2022-01-01",
        role="Voorzitter",
        periods=[
            {"from_date": "2020-01-01", "to_date": "2021-01-01", "role": "Lid"},
            {"from_date": "2022-01-01", "role": "Voorzitter"},
        ],
    )
    g.edge(member, "MEMBER_OF", fin, from_date="2018-01-01", to_date="2019-01-01")
    g.edge(
        member,
        "MEMBER_OF",
        ek,
        role="voorzitter",
        observed_from="2026-09-30",
        observed_until=None,
    )
    g.write()

    rows = get_member_committees(store, member)
    # those they sit on now first, then by name
    assert [r["key"] for r in rows] == ["ek_fin", "jv", "fin"]
    from lawgraph.api.schemas.committees import MemberCommitteeDTO

    jv_seat = MemberCommitteeDTO.from_row(rows[1]).model_dump()
    assert jv_seat["role"] == "Voorzitter" and jv_seat["chamber"] == "TK"
    assert [p["role"] for p in jv_seat["periods"]] == ["Lid", "Voorzitter"]
    assert MemberCommitteeDTO.from_row(rows[0]).chamber == "EK"
    assert MemberCommitteeDTO.from_row(rows[2]).to_date == "2019-01-01"
    assert get_member_committees(store, "members/none") == []
