"""The committee, member and faction queries on a real PostgreSQL: the committees with their
members, dossiers and activities, the member and faction lists, the seats on a day, a
member's votes, the laws an actor changes, the dossiers an actor authored in and the votes of
a faction of the Eerste Kamer; and the routes in front of them."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
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
    RELATION_REFERS_TO,
    RELATION_REPEALS,
    RELATION_VOTED,
)
from lawgraph.core.models import Node
from lawgraph.core.tk_records.decisions import VOTE_KIND_MEMBER
from lawgraph.db import GraphStore, NodeWriter, version_cache
from lawgraph.db.queries import member_votes
from lawgraph.db.queries._json_sql import array_or_empty, is_absent
from lawgraph.db.queries._parliament_sql import IN_MEMBERSHIP
from lawgraph.db.queries.actors import get_actor_dossiers, get_actor_touched_instruments
from lawgraph.db.queries.committees import (
    get_committee_activities,
    get_committee_detail,
    get_committees,
)
from lawgraph.db.queries.factions import (
    get_ek_faction_votes,
    get_factions,
    get_seats_on,
)
from lawgraph.db.queries.member_votes import get_member_votes
from lawgraph.db.queries.members import (
    count_members,
    get_ek_members,
    get_member_committees,
    get_members,
)
from tests.asserts import assert_status, show_items
from tests.fakes import assert_fast
from tests.pg.committee_graph import (
    CO,
    D66,
    FIRST,
    VVD,
    Graph,
    authorship_graph,
    candidates_plan,
    committee_graph,
    decisions_voted,
    faction_graph,
    people_graph,
    signatures,
    write_votes,
)
from tests.pg.plans import explain, plan_nodes, recorded


def _keys(docs: list[dict[str, Any]]) -> list[str]:
    return [doc["key"] for doc in docs]


@pytest.fixture()
def client(store: GraphStore) -> Iterator[TestClient]:
    app.dependency_overrides[get_store] = lambda: store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_store, None)


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
    assert list(tk[0]) == ["key", "id", "type", "labels", "props"]
    assert tk[0]["id"] == "committees/c_a"
    assert _keys(get_committees(store, chamber="EK")) == ["ek_fin"]


def test_a_committee_by_slug_or_key_the_key_settling_a_slug_that_is_a_key(
    store: GraphStore,
) -> None:
    committee_graph(store)
    for slug in ("b", "B", "c_b", "C_B"):
        found = get_committee_detail(store, slug)
        assert found is not None and found["key"] == "c_b"
    # ``x`` is the slug of ``zz`` and the key of ``x``: the lower key wins
    found = get_committee_detail(store, "x")
    assert found is not None and found["key"] == "x"
    assert get_committee_detail(store, "nope") is None
    assert get_committee_activities(store, "nope") is None


def test_the_members_of_a_committee_by_name_then_key_with_their_seat(
    store: GraphStore,
) -> None:
    committee_graph(store)
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


def test_the_members_of_a_committee_the_data_has_no_seat_on_are_not_known(
    store: GraphStore,
) -> None:
    """B11: a committee no seat in the data is on has members that are not known (None),
    not none; one whose seats all ended has none now."""
    committee_graph(store)
    unseated = get_committee_detail(store, "ix")
    assert unseated is not None and unseated["members"] is None
    every = get_committee_detail(store, "ix", current_only=False)
    assert every is not None and every["members"] is None
    store.execute(
        "DELETE FROM edges WHERE to_id = 'committees/c_b' AND relation = 'MEMBER_OF'"
        " AND from_id <> 'members/m2'"
    )
    ended = get_committee_detail(store, "b")
    assert ended is not None and ended["members"] == []


def test_the_dossiers_of_a_committee_newest_opened_first_by_status_and_paged(
    store: GraphStore,
) -> None:
    committee_graph(store)
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
    committee_graph(store)
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
    # ``dossier_numbers`` when it is a list, else []: "", an object and a missing one
    numbers = {row["key"]: row["dossier_numbers"] for row in page["items"]}
    assert numbers == {"a1": ["36000"], "a2": [], "a5": [], "a6": [], "a3": []}

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
    assert [d["key"] for d in everything["dossiers"]] == [
        "37004",
        "37003",
    ]  # newest opened

    second = get_committee_detail(store, "A", limit=2, offset=2)
    assert second is not None
    assert [d["key"] for d in second["dossiers"]] == ["37002", "37001"]

    of_closed = get_committee_detail(store, "a", status="closed")
    assert of_closed is not None
    assert of_closed["dossier_total"] == 2
    assert {d["key"] for d in of_closed["dossiers"]} == {"37003", "37004"}

    opened = get_committee_detail(store, "a", status="open")
    assert opened is not None
    assert opened["dossier_total"] == 3
    assert {d["key"] for d in opened["dossiers"]} == {"37000", "37001", "37002"}

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


def test_members_who_held_a_seat_by_name_then_key(store: GraphStore) -> None:
    people_graph(store)
    assert _keys(get_members(store)) == ["m1", "m2", "Zz", "m3", "m6"]
    everyone = get_members(store, include_all=True)
    assert _keys(everyone) == ["m1", "m2", "Zz", "m3", "m4", "m6", "m9", "m7"]
    assert list(everyone[0]) == ["key", "id", "type", "labels", "props"]
    assert _keys(get_members(store, government=True)) == ["m4", "m7"]
    assert _keys(get_members(store, cabinet="cab1")) == ["m4", "m7"]
    assert _keys(get_members(store, cabinet="cab2")) == ["m7"]
    page = get_members(store, include_all=True, limit=3, offset=2)
    assert _keys(page) == ["Zz", "m3", "m4"]
    assert get_members(store, include_all=True, offset=100) == []
    assert count_members(store) == 5
    assert count_members(store, include_all=True) == len(everyone)
    assert count_members(store, government=True) == 2


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
    people_graph(store)
    # the party, or an abbreviation, name or alias in the timeline, in any case
    assert _keys(get_members(store, party=" vvd ")) == ["m1", "m2", "Zz", "m3"]
    assert _keys(get_members(store, party="volkspartij")) == ["m1", "m2", "Zz", "m3"]
    assert _keys(get_members(store, party="democraten 66")) == ["m1", "m6"]
    assert get_members(store, party="cda") == []
    # seated: a membership without an end
    assert _keys(get_members(store, active=True)) == ["m1", "m2", "Zz", "m6"]
    assert _keys(get_members(store, active=False)) == ["m3"]
    # seated and of a party: seated for it now. m1 left the VVD for D66: still of the
    # VVD's history (above), but no VVD member now; the VVD counts m2 and Zz
    assert _keys(get_members(store, party="VVD", active=True)) == ["m2", "Zz"]
    assert _keys(get_members(store, party="d66", active=True)) == ["m1", "m6"]
    assert _keys(get_members(store, party="volkspartij", active=False)) == ["m3"]
    # a name part, in any case, also beyond ASCII; nothing contains ""
    assert _keys(get_members(store, q="ann")) == ["m1", "m2", "Zz"]
    assert _keys(get_members(store, q="émile", include_all=True)) == ["m6", "m9"]
    # and without its accents, or in capitals: folded on both sides as the search folds
    for q in ("emile", "EMILE", "ÉMILE"):
        assert _keys(get_members(store, q=q, include_all=True)) == ["m6", "m9"], q
    assert get_members(store, q="  ") == []


def test_the_members_of_the_eerste_kamer(store: GraphStore) -> None:
    people_graph(store)
    # one without a name comes first
    assert _keys(get_ek_members(store)) == ["m8", "m6", "m7"]
    assert _keys(get_ek_members(store, active=True)) == ["m8", "m6"]
    assert _keys(get_ek_members(store, active=False)) == ["m7"]
    assert _keys(get_ek_members(store, party="VVD")) == ["m8", "m6"]
    assert _keys(get_ek_members(store, q="émile e")) == ["m6"]
    assert _keys(get_ek_members(store, q="Emile E")) == ["m6"]
    assert _keys(get_ek_members(store, q="zo")) == ["m7"]
    assert get_ek_members(store, q=" ") == []
    assert _keys(get_ek_members(store, limit=1, offset=1)) == ["m6"]


def _plan(store: GraphStore, call: Any) -> str:
    """The plan PostgreSQL makes for the one statement *call* runs on *store*."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        seen = recorded(store, monkeypatch)
        call()
    [(statement, params, *_)] = seen
    with store.pool.connection() as conn:
        conn.execute(b"ANALYZE members")
        assert isinstance(statement, str)
        rows = conn.execute(("EXPLAIN " + statement).encode(), params).fetchall()
    return "\n".join(row[0] for row in rows)


def test_a_page_of_members_is_read_from_an_index_in_name_order(
    store: GraphStore,
) -> None:
    """The lists filter and sort on columns (``list_name``, ``in_parliament``, ``in_ek``):
    a page is read from a partial index in name order, not from every member's props."""
    people_graph(store)
    g = Graph(store)
    for n in range(3000):  # people who never held a seat: what the TK lists most
        g.node("members", f"filler{n:04d}", name=f"Iemand {n}")
    g.write()
    tk = _plan(store, lambda: get_members(store, limit=5))
    assert "members_list_name" in tk and "Seq Scan" not in tk
    ek = _plan(store, lambda: get_ek_members(store, limit=5))
    assert "members_list_ek" in ek and "Seq Scan" not in ek
    assert _keys(get_members(store, limit=2)) == ["m1", "m2"]


def test_factions_seated_first_by_abbreviation_name_and_key_with_their_members(
    store: GraphStore,
) -> None:
    faction_graph(store)
    factions = get_factions(store)
    # seated, then not, then unknown; no abbreviation before one; a name settles one
    assert _keys(factions) == ["d66", "z", "vvd", "cda", "none"]
    counts = {doc["key"]: doc["member_count"] for doc in factions}
    assert counts == {"d66": 1, "z": 0, "vvd": 3, "cda": 0, "none": 0}
    failing = [count for count in counts.values() if type(count) is not int]
    assert not failing, show_items(failing)
    assert list(factions[0]) == [
        "key",
        "id",
        "type",
        "labels",
        "props",
        "member_count",
    ]
    assert _keys(get_factions(store, active=True)) == ["d66", "z", "vvd"]
    assert _keys(get_factions(store, active=False)) == ["cda"]
    assert _keys(get_factions(store, q="d6")) == ["d66", "z"]
    assert _keys(get_factions(store, q="ZET")) == ["z"]
    assert _keys(get_factions(store, q="zéta")) == ["z"]  # an accent the name lacks
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


def test_a_member_votes_by_roll_call_and_through_the_factions_of_the_day(
    store: GraphStore,
) -> None:
    write_votes(store)
    votes = get_member_votes(store, "members/m1")
    # newest first; one day settled by key, then the member's own vote before the
    # faction's; the undated last
    # an own vote under the faction the member sat in that day; the undated under none
    assert [(v["decision_key"], v["faction_key"], v["vote_source"]) for v in votes] == [
        ("s0", "d66", "member"),
        ("s0", "d66", "faction"),
        ("s1", "d66", "faction"),
        ("s3", "d66", "member"),
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
            "in_office": [],
            # no cabinet in the data: no coalition
            "coalition": None,
            "coalition_factions": [],
        }
    )
    # every vote carries the party of the day; an undated own vote the one they sit for now
    assert votes[0]["party"] == "D66" and votes[4]["party"] == "VVD"
    assert votes[5]["party"] == "D66"
    assert votes[2]["external_id"] == "b1" and type(votes[2]["seats"]) is int
    assert len(get_member_votes(store, "members/m1", limit=2)) == 2
    assert get_member_votes(store, "members/nobody") == []


def test_a_vote_cast_in_office_names_the_posts_held_that_day(store: GraphStore) -> None:
    """A Kamerlid who is also a (demissionary) bewindspersoon: each vote names the posts
    of ``government_functions`` held on its date, both days included; none outside."""
    g = Graph(store)
    klimaat = {
        "function": "Minister voor Klimaat en Energie",
        "cabinet_key": "rutte_iv",
        "cabinet": "kabinet-Rutte IV",
        "from_date": "2022-01-10",
        "to_date": "2024-07-02",
    }
    vice = {
        **klimaat,
        "function": "viceminister-president",
        "from_date": "2024-01-12",
    }
    g.node(
        "members",
        "m1",
        name="Rob",
        party="D66",
        faction_memberships=[{**D66, "from_date": "2023-12-06"}],
        government_functions=[vice, klimaat],
    )
    g.node("factions", "d66", name="D66")
    for key, date in (
        ("v1", "2024-01-11"),
        ("v2", "2024-01-12"),
        ("v3", "2024-07-02"),
        ("v4", "2024-07-03"),
    ):
        g.node("decisions", key, date=date)
        g.edge("factions/d66", RELATION_VOTED, f"decisions/{key}", choice="Voor")
    g.node("decisions", "r1", date="2024-03-01", vote_kind=VOTE_KIND_MEMBER)
    g.edge("members/m1", RELATION_VOTED, "decisions/r1", choice="Tegen", seats=1)
    g.write()

    def posts(vote: dict[str, Any]) -> list[str]:
        return [p["function"] for p in vote["in_office"]]

    votes = {v["decision_key"]: v for v in get_member_votes(store, "members/m1")}
    assert posts(votes["v4"]) == []
    # the oldest post first
    assert posts(votes["v3"]) == [klimaat["function"], vice["function"]]
    assert posts(votes["r1"]) == [klimaat["function"], vice["function"]]
    assert posts(votes["v2"]) == [klimaat["function"], vice["function"]]
    assert posts(votes["v1"]) == [klimaat["function"]]
    assert votes["v1"]["in_office"] == [
        {
            "function": "Minister voor Klimaat en Energie",
            "cabinet_key": "rutte_iv",
            "cabinet": "kabinet-Rutte IV",
        }
    ]


def test_the_votes_of_a_member_page_by_offset_and_by_being_in_office(
    store: GraphStore,
) -> None:
    """``offset`` pages the votes (it was ignored: every page was the first), and
    ``in_office`` keeps the votes cast in office alone, before the page is cut (the
    explorer counted those of the first 50: "20 stemmen" for Rutte, who has many more)."""
    from fastapi.testclient import TestClient

    from lawgraph.api.app import app
    from lawgraph.api.dependencies import get_store

    test_a_vote_cast_in_office_names_the_posts_held_that_day(store)

    def keys(**params: Any) -> list[str]:
        return [
            v["decision_key"] for v in get_member_votes(store, "members/m1", **params)
        ]

    # newest first: v4 (out of office), v3, r1 (a roll-call), v2, v1
    assert keys(limit=2) == ["v4", "v3"]
    assert keys(limit=2, offset=2) == ["r1", "v2"]
    assert keys(limit=2, offset=4) == ["v1"]
    assert keys(limit=3, in_office=True) == ["v3", "r1", "v2"]
    assert keys(limit=3, offset=3, in_office=True) == ["v1"]
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        first = client.get("/api/members/m1/votes", params={"limit": 2}).json()
        office = client.get(
            "/api/members/m1/votes",
            params={"limit": 3, "offset": 3, "in_office": "true"},
        ).json()
    finally:
        app.dependency_overrides.pop(get_store, None)
    assert [v["decision_key"] for v in first["votes"]] == ["v4", "v3"]
    assert first["next_offset"] == 2
    assert [v["decision_key"] for v in office["votes"]] == ["v1"]
    assert office["next_offset"] is None


def test_an_own_vote_of_before_carries_the_faction_of_its_day(
    store: GraphStore,
) -> None:
    """A roll-call of the years the member sat for another faction (Mona Keijzer's of the
    CDA, now "Lid Keijzer"): the faction and party of that day, as a faction's vote has,
    not the party they sit for now, and never no faction at all."""
    g = Graph(store)
    g.node("members", "m1", name="Mona", party="Lid Keijzer", faction_memberships=[
        {**VVD, "faction_key": "cda", "faction_id": "factions/cda", "abbreviation": "CDA",
         "from_date": "2012-09-20", "to_date": "2017-10-25"},
        {**D66, "faction_key": "lid_keijzer", "faction_id": "factions/lid_keijzer",
         "abbreviation": "Lid Keijzer", "from_date": "2026-02-24", "to_date": None},
    ])  # fmt: skip
    g.node("decisions", "old", date="2015-06-01", vote_kind=VOTE_KIND_MEMBER)
    g.node("decisions", "new", date="2026-10-08", vote_kind=VOTE_KIND_MEMBER)
    g.edge("members/m1", RELATION_VOTED, "decisions/old", choice="Voor", seats=1)
    g.edge("members/m1", RELATION_VOTED, "decisions/new", choice="Tegen", seats=1)
    g.write()
    votes = {v["decision_key"]: v for v in get_member_votes(store, "members/m1")}
    assert (votes["old"]["faction_key"], votes["old"]["party"]) == ("cda", "CDA")
    assert (votes["new"]["faction_key"], votes["new"]["party"]) == (
        "lid_keijzer",
        "Lid Keijzer",
    )
    assert {v["vote_source"] for v in votes.values()} == {"member"}


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
                   CASE WHEN {is_absent("f.period -> 'abbreviation'")}
                        THEN f.period -> 'name' ELSE f.period -> 'abbreviation' END,
                   f.period -> 'faction_key', f.period ->> 'faction_key',
                   'faction'::text
            FROM member
            CROSS JOIN LATERAL json_array_elements(
                {array_or_empty("member.props -> 'faction_memberships'")}
            ) AS f(period)
            JOIN {COLLECTION_EDGES} e
              ON e.from_id = f.period ->> 'faction_id' AND e.relation = %(voted)s
            JOIN {COLLECTION_DECISIONS} d ON d.id = e.to_id
            WHERE d.date IS NOT NULL
              AND lg_str(d.props -> 'vote_kind') IS DISTINCT FROM %(roll_call)s
              AND {IN_MEMBERSHIP}
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
        kind: dict[str, Any] = {"vote_kind": VOTE_KIND_MEMBER} if roll_call else {}
        g.node("decisions", key, date=date, **kind)
        for faction in ("factions/vvd", "factions/d66"):
            g.edge(faction, RELATION_VOTED, f"decisions/{key}", choice="Voor", seats=9)
        if roll_call and n % 12 != 11:
            g.edge("members/m1", RELATION_VOTED, f"decisions/{key}", choice="Tegen")
    g.write()


@pytest.mark.parametrize("candidates", [member_votes.VOTE_CANDIDATES, 1])
def test_the_newest_votes_are_those_of_every_vote(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch, candidates: int
) -> None:
    """The votes of a faction read newest first, before the roll-calls among them are
    known, answer what reading every vote answered; with too few read (a page of
    roll-calls) the statement reads more."""
    _many_votes(store)
    monkeypatch.setattr(member_votes, "VOTE_CANDIDATES", candidates)
    for limit in (1, 7, 50, 100):
        new = get_member_votes(store, "members/m1", limit=limit)
        # the posts held that day came later (a member without any here)
        failing = [v for v in new if v.pop("in_office") != []]
        assert not failing, show_items(failing)
        failing_2 = [v for v in new if v.pop("coalition") is not None]
        assert not failing_2, show_items(failing_2)
        failing_3 = [v for v in new if v.pop("coalition_factions") != []]
        assert not failing_3, show_items(failing_3)
        # an own vote took the party of now there, and no faction: the day's here
        old = _old_member_votes(store, "members/m1", limit)
        for votes_ in (new, old):
            for v in votes_:
                if v["vote_source"] == "member":
                    v.pop("party"), v.pop("faction_key")
        assert new == old, limit
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
    decisions: dict[str, dict[str, Any]] = {
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
    to = get_ek_faction_votes(store, "VVD", to_date="2023-12-31")
    assert [i["decision_key"] for i in to["items"]] == ["e6", "e3"]
    since = get_ek_faction_votes(store, "VVD", from_date="2022-01-01")
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
    g.edge("documents/doc3", RELATION_REFERS_TO, "articles/a1")  # not a change
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


def test_a_member_and_a_faction_list_the_dossiers_they_authored_in(
    store: GraphStore,
) -> None:
    authorship_graph(store)

    member = get_actor_dossiers(store, "members/m1")
    assert member["total"] == 2
    first, second = member["items"]  # newest opened first
    assert first["dossier"]["key"] == "38002"
    assert first["roles"] == ["Eerste ondertekenaar"] and first["document_count"] == 1
    assert second["dossier"]["key"] == "38001"
    assert second["roles"] == ["Eerste ondertekenaar", "Mede ondertekenaar"]
    assert second["document_count"] == 2

    page = get_actor_dossiers(store, "members/m1", limit=1, offset=1)
    assert page["total"] == 2 and [r["dossier"]["key"] for r in page["items"]] == [
        "38001"
    ]

    # A faction counts what its members signed while they belonged to it.
    vvd = get_actor_dossiers(store, "factions/vvd")
    assert vvd["total"] == 1
    assert vvd["items"][0]["dossier"]["key"] == "38001"
    assert vvd["items"][0]["document_count"] == 2  # both old motions, by two members
    assert vvd["items"][0]["roles"] == ["Eerste ondertekenaar", "Mede ondertekenaar"]

    d66 = get_actor_dossiers(store, "factions/d66")
    assert d66["total"] == 1 and d66["items"][0]["dossier"]["key"] == "38002"

    assert get_actor_dossiers(store, "members/nobody") == {"total": 0, "items": []}


def test_the_dossiers_of_an_actor_carry_distinct_roles_functions_and_capacities(
    store: GraphStore,
) -> None:
    signatures(store)

    result = get_actor_dossiers(store, "members/m1")
    assert list(result) == ["total", "items"] and result["total"] == 3
    # one opening day settled by key, the undated last
    assert [row["dossier"]["key"] for row in result["items"]] == ["d1", "d2", "d3"]
    d1 = result["items"][0]
    assert list(d1) == ["dossier", "roles", "functions", "capacities", "document_count"]
    # "" is no role, function or capacity
    assert d1["roles"] == [FIRST]
    assert d1["functions"] == ["minister"]
    assert d1["capacities"] == ["bewindspersoon"]
    assert d1["document_count"] == 2 and type(d1["document_count"]) is int
    assert result["items"][2]["capacities"] == []

    # a faction: on the day of the document or case, from the member's start
    vvd = get_actor_dossiers(store, "factions/vvd")
    assert [row["dossier"]["key"] for row in vvd["items"]] == ["d1", "d2", "d3"]
    assert vvd["items"][0]["roles"] == [CO]
    assert get_actor_dossiers(store, "members/m1", offset=10) == {
        "total": 3,
        "items": [],
    }


def test_an_empty_capacity_and_an_object_of_dossiers_answer_their_routes(
    store: GraphStore, client: TestClient
) -> None:
    """A signature with capacity "" and an activity with ``dossier_numbers`` ``{}``: the
    routes leave them out and answer."""
    signatures(store)
    committee_graph(store)

    member = client.get("/api/members/m1/dossiers")
    assert_status(member, 200)
    assert member.json()["items"][0]["capacities"] == ["bewindspersoon"]

    activities = client.get("/api/committees/b/activities")
    assert_status(activities, 200)
    numbers = {i["key"]: i["dossier_numbers"] for i in activities.json()["items"]}
    assert numbers["a6"] == []


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

    result = assert_fast(lambda: get_actor_dossiers(store, faction, limit=10))
    page = assert_fast(
        lambda: get_committee_activities(store, "a", limit=10, offset=100)
    )

    assert result["total"] == 50 and len(result["items"]) == 10
    assert (
        result["items"][0]["document_count"] == 300
    )  # 15,000 documents over 50 dossiers
    assert page is not None and page["total"] == 3000 and len(page["items"]) == 10


def test_a_committee_page_is_read_once_per_data_version(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The dossiers and the activities a committee leads walk every edge of it (6 s and
    2.6 s for Financiën on prod): kept until the data changes."""
    from lawgraph.db.queries import committees

    committee_graph(store)
    read: list[str] = []
    for name in ("_led_dossiers", "_led_activities"):
        real = getattr(committees, name)

        def counted(*args: Any, _real: Any = real, _name: str = name, **kw: Any) -> Any:
            read.append(_name)
            return _real(*args, **kw)

        monkeypatch.setattr(committees, name, counted)
    first = get_committee_detail(store, "b")
    assert get_committee_detail(store, "b") == first
    activities = get_committee_activities(store, "b")
    assert get_committee_activities(store, "b") == activities
    assert read == ["_led_dossiers", "_led_activities"]
    # a write raises the data version: read again
    more = Graph(store)
    more.edge("activities/a1", RELATION_ABOUT, "dossiers/d3")
    more.write()
    get_committee_detail(store, "b")
    assert read[-1] == "_led_dossiers"


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
    authorship_graph(store)

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


def test_a_page_of_a_factions_dossiers_is_read_once_per_version_of_its_tables(
    store: GraphStore, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two equal requests read the dossiers once; another page, or a write to a table they
    read, reads again; an unknown faction is a 404."""
    from lawgraph.api import actors

    authorship_graph(store)
    reads: list[tuple[str, int, int]] = []
    read = get_actor_dossiers

    def counted(store_: Any, actor_id: str, *, limit: int, offset: int) -> Any:
        reads.append((actor_id, limit, offset))
        return read(store_, actor_id, limit=limit, offset=offset)

    monkeypatch.setattr(actors, "get_actor_dossiers", counted)
    first = client.get("/api/factions/vvd/dossiers").json()
    assert client.get("/api/factions/vvd/dossiers").json() == first
    assert reads == [("factions/vvd", 100, 0)]

    client.get("/api/factions/vvd/dossiers?offset=1")
    assert reads[-1] == ("factions/vvd", 100, 1)
    g = Graph(store)
    g.node("dossiers", "39999", number="39999")
    g.write()
    assert client.get("/api/factions/vvd/dossiers").json() == first
    assert len(reads) == 3
    assert_status(client.get("/api/factions/nobody/dossiers"), 404)


def test_walking_the_pages_of_the_members_finds_every_row_once(
    store: GraphStore, client: TestClient
) -> None:
    """60 members of one name."""
    rows = 60
    with NodeWriter(store) as writer:
        writer.add_all(
            Node(
                collection="members",
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
    from lawgraph.api.schemas.members import MemberCommitteeDTO

    jv_seat = MemberCommitteeDTO.from_row(rows[1]).model_dump()
    assert jv_seat["role"] == "Voorzitter" and jv_seat["chamber"] == "TK"
    assert [p["role"] for p in jv_seat["periods"]] == ["Lid", "Voorzitter"]
    assert MemberCommitteeDTO.from_row(rows[0]).chamber == "EK"
    assert MemberCommitteeDTO.from_row(rows[2]).to_date == "2019-01-01"
    assert get_member_committees(store, "members/none") == []


def test_the_votes_of_an_old_period_start_at_its_end(store: GraphStore) -> None:
    """The read of the votes of a period that ended long ago starts at its end, not at the
    newest vote: its bounds are conditions of the index (an old period of a member on prod
    passed 30,000 newer decisions, each tested and dropped)."""
    old = {**VVD, "from_date": "2020-01-01", "to_date": "2020-12-31"}
    new = {**D66, "from_date": "2021-01-01", "to_date": "2021-03-31"}
    decisions_voted(store, [old, new])
    nodes = candidates_plan(store, "members/m1", 10)
    dates = [n for n in nodes if n.get("Index Name") == "lg_faction_votes_period"]
    assert dates, [(n["Node Type"], n.get("Index Name")) for n in nodes]
    for scan in dates:
        assert ">=" in scan["Index Cond"] and "<=" in scan["Index Cond"], scan
        # the decisions of 2022-2025 (2,000) are never read, so none is dropped
        dropped = scan.get("Rows Removed by Filter", 0) * scan["Actual Loops"]
        assert dropped < 50, dropped


def test_the_page_of_votes_reads_the_edges_of_its_votes_alone(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The page is chosen from the candidates by their dates before any edge's meta is read
    (each candidate read its edge: 1,800 for a page of 100 on prod, 3.3 s cold), and the kind
    of each vote comes from the decision the walk read (a second join of the decisions for
    it was planned as a read of all 94,000)."""
    decisions_voted(store, [D66])
    calls = recorded(store, monkeypatch)
    assert len(get_member_votes(store, "members/m1", limit=10)) == 10
    statement, params, *_ = [c for c in calls if c.params and "candidates" in c.params][
        0
    ]
    plan = explain(store, statement, params, analyze=True)
    nodes = list(plan_nodes(plan))
    by_key = [n for n in nodes if n.get("Index Name") == "edges_pkey"]
    assert sum(n["Actual Rows"] * n["Actual Loops"] for n in by_key) <= 10
    assert not [
        n
        for n in nodes
        if n.get("Relation Name") == "decisions" and "vote_kind" in n.get("Filter", "")
    ]


def test_a_faction_reads_its_dossiers_from_the_kept_signatures(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A faction reads what its members signed from ``lg_authored`` (the dossiers and the
    date of each paper kept with it), never the edges of every signature; a fill of an
    empty table gives the same page as the triggers kept."""
    from lawgraph.db.queries import member_authored

    authorship_graph(store)
    signatures(store)
    seen = recorded(store, monkeypatch)
    kept = {f: get_actor_dossiers(store, f) for f in ("factions/vvd", "factions/d66")}
    statements = [c.text for c in seen if "grouped AS" in c.text]
    assert len(statements) == 2
    for statement in statements:
        assert "lg_authored" in statement
        assert "AUTHORED" not in statement

    store.execute("DELETE FROM lg_authored")  # as written before the triggers
    member_authored.fill_authored(store)
    version_cache.clear()
    for faction, page in kept.items():
        assert get_actor_dossiers(store, faction) == page
