"""The votes of the factions with their decisions' dates, on a real PostgreSQL:
``lg_faction_votes`` kept by the triggers on every write of ``edges`` and ``decisions``,
filled by ``semantic graph-light`` for the votes written before them, and read by the page of
a member's votes (``get_member_votes``) once filled, the same page as the walk over the
decisions gives, a vote of today included."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from lawgraph.config.constants import RELATION_REFERS_TO, RELATION_VOTED
from lawgraph.core.tk_records import VOTE_KIND_MEMBER
from lawgraph.db import GraphStore
from lawgraph.db.queries import faction_votes
from lawgraph.db.queries.committees import get_member_votes
from tests.pg.test_committees_queries import D66, VVD, Graph, _decisions_voted, _votes


def _rows(store: GraphStore) -> list[tuple[Any, ...]]:
    return [
        (r["faction_id"], r["decision_key"], r["date"], r["vote_kind"])
        for r in store.query(
            "SELECT faction_id, decision_key, date, vote_kind FROM lg_faction_votes"
            " ORDER BY faction_id, decision_key"
        )
    ]


def test_a_vote_of_a_faction_is_kept_with_its_decision(store: GraphStore) -> None:
    """Written with the edge, also when the decision comes after it; changed with the
    decision; gone with the edge or the decision. Votes of members and other edges are
    not kept."""
    g = Graph(store)
    g.node("factions", "vvd", name="VVD")
    g.node("members", "m1", name="Anna")
    g.node("decisions", "s1", date="2024-01-01")
    g.edge("factions/vvd", RELATION_VOTED, "decisions/s1", choice="Voor")
    g.edge("members/m1", RELATION_VOTED, "decisions/s1", choice="Voor")
    g.edge("factions/vvd", RELATION_REFERS_TO, "decisions/s1")
    g.write()
    assert _rows(store) == [("factions/vvd", "s1", "2024-01-01", None)]

    # a vote whose decision is written after it
    g.edge("factions/vvd", RELATION_VOTED, "decisions/s2", choice="Tegen")
    g.write()
    assert len(_rows(store)) == 1
    g.node("decisions", "s2", date="2024-02-01", vote_kind=VOTE_KIND_MEMBER)
    g.write()
    assert _rows(store)[1] == ("factions/vvd", "s2", "2024-02-01", VOTE_KIND_MEMBER)

    # the decision's date changes
    g.node("decisions", "s1", date="2024-01-05")
    g.write()
    assert _rows(store)[0][2] == "2024-01-05"

    store.execute("DELETE FROM decisions WHERE id = 'decisions/s2'")
    store.execute(
        "DELETE FROM edges WHERE from_id = 'factions/vvd' AND to_id = 'decisions/s1'"
        " AND relation = 'VOTED'"
    )
    assert _rows(store) == []


def test_the_page_is_read_from_the_table_only_once_it_is_filled(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Before the fill the votes written before the triggers are not in it: the page walks
    the decisions until ``graph-light`` filled it (in batches) and noted so."""
    _votes(store)
    walked = get_member_votes(store, "members/m1")
    store.execute("DELETE FROM lg_faction_votes")  # as written before the triggers
    assert not faction_votes.is_filled(store)
    assert get_member_votes(store, "members/m1") == walked
    monkeypatch.setattr(faction_votes, "BATCH", 2)
    assert faction_votes.fill_faction_votes(store) == 8
    assert faction_votes.is_filled(store)
    assert faction_votes.fill_faction_votes(store) == 0
    assert faction_votes.fill_faction_votes(store, every=True) == 8
    assert get_member_votes(store, "members/m1") == walked


@pytest.mark.parametrize(
    "memberships",
    [
        [D66],
        [VVD, D66],
        [
            {**VVD, "from_date": "2020-01-01", "to_date": "2020-12-31"},
            {**D66, "from_date": "2021-01-01", "to_date": "2021-03-31"},
        ],
    ],
)
def test_the_page_from_the_table_is_that_of_the_walk(
    store: GraphStore, memberships: list[dict[str, Any]]
) -> None:
    """For periods new and old, and pages small and past the candidates of a period (with
    roll-calls among them, read again with more), the same votes in the same order."""
    _decisions_voted(store, memberships)
    for n in range(
        0, 3000, 7
    ):  # some roll-calls: the member's own vote, not the faction's
        store.execute(
            "UPDATE decisions SET props = json_build_object('date', props -> 'date',"
            " 'vote_kind', %(kind)s::text) WHERE id = %(id)s",
            {"kind": VOTE_KIND_MEMBER, "id": f"decisions/s{n:04d}"},
        )
    pages = {
        limit: get_member_votes(store, "members/m1", limit=limit)
        for limit in (1, 10, 150, 500)
    }
    faction_votes.fill_faction_votes(store)
    for limit, walked in pages.items():
        assert get_member_votes(store, "members/m1", limit=limit) == walked, limit


def test_a_vote_of_today_is_on_the_page_at_once(store: GraphStore) -> None:
    """The table is kept by the write itself: a vote of today shows before any run."""
    _votes(store)
    faction_votes.fill_faction_votes(store)
    today = dt.date.today().isoformat()
    g = Graph(store)
    g.node("decisions", "today", date=today, subject="Motie van vandaag")
    g.edge("factions/d66", RELATION_VOTED, "decisions/today", choice="Voor", seats=9)
    g.write()
    newest = get_member_votes(store, "members/m1", limit=1)[0]
    assert (newest["decision_key"], newest["date"], newest["faction_key"]) == (
        "today",
        today,
        "d66",
    )


def test_a_member_of_both_chambers_has_their_votes_of_both(store: GraphStore) -> None:
    """The votes through a faction of the Tweede Kamer and their own votes by roll-call in
    the Eerste Kamer, both on the page."""
    _votes(store)
    g = Graph(store)
    g.node("decisions", "ek1", date="2025-03-04", chamber="EK")
    g.edge("members/m1", RELATION_VOTED, "decisions/ek1", choice="Voor", seats=1)
    g.write()
    faction_votes.fill_faction_votes(store)
    votes = get_member_votes(store, "members/m1")
    assert ("ek1", "member") in {(v["decision_key"], v["vote_source"]) for v in votes}
    assert ("s1", "faction") in {(v["decision_key"], v["vote_source"]) for v in votes}


def test_the_faction_votes_of_a_period_are_a_range_of_the_table(
    store: GraphStore,
) -> None:
    """Once filled, the candidates of a period come from the index of the table, not from a
    walk over the decisions with a probe of the edges per decision (5.7 s cold on prod)."""
    from tests.pg.test_committees_queries import _candidates_plan

    _decisions_voted(store, [D66])
    faction_votes.fill_faction_votes(store)
    nodes = _candidates_plan(store, "members/m1", 10)
    relations = {n.get("Relation Name") for n in nodes} - {None}
    assert relations == {"lg_faction_votes"}, relations
    read = sum(
        n["Actual Rows"] * n["Actual Loops"] for n in nodes if n.get("Relation Name")
    )
    assert read <= 20, read
