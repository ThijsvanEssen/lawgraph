"""What the coalition did on each vote, for real: ``semantic tk-coalition-votes`` over
decisions with faction votes (with their seats) and a roll call, the coalition of the
cabinet in office that day, and the list, the facet and the detail of decisions."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import RELATION_ABOUT, RELATION_SERVED_IN, RELATION_VOTED
from lawgraph.db import GraphStore, make_edge_doc


def _node(
    key: str, node_type: str, labels: list[str] | None = None, **props: Any
) -> dict:
    return {"_key": key, "type": node_type, "labels": labels or [], "props": props}


def _vote(voter: str, decision: str, choice: str, seats: int = 0) -> dict[str, Any]:
    return make_edge_doc(
        voter,
        f"decisions/{decision}",
        RELATION_VOTED,
        source="t",
        meta={"choice": choice, "seats": seats},
    )


def _seed(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "cabinets",
        [_node("schoof", "cabinet", name="kabinet-Schoof", from_date="2024-07-02")],
    )
    store.bulk_insert_or_update_nodes(
        "factions",
        [
            _node(k, "faction", name=k.upper(), abbreviation=k.upper())
            for k in ("pvv", "vvd", "gl", "sp")
        ],
    )
    store.bulk_insert_or_update_nodes(
        "members",
        [
            _node("minister_pvv", "member", name="m1"),
            _node("minister_vvd", "member", name="m2"),
            _node(
                "kamerlid_vvd",
                "member",
                name="k1",
                faction_memberships=[
                    {"faction_key": "vvd", "from_date": "2023-12-06", "to_date": None}
                ],
            ),
            _node(
                "kamerlid_gl",
                "member",
                name="k2",
                faction_memberships=[
                    {"faction_key": "gl", "from_date": "2023-12-06", "to_date": None}
                ],
            ),
        ],
    )
    posts = {
        "minister_pvv": {
            "party": {"short": "PVV", "faction": "pvv"},
            "from_date": "2024-07-02",
            "to_date": "2025-06-03",
        },
        "minister_vvd": {
            "party": {"short": "VVD", "faction": "vvd"},
            "from_date": "2024-07-02",
            "to_date": None,
        },
    }
    store.bulk_insert_or_update_nodes(
        "decisions",
        [
            _node(
                "together",
                "decision",
                ["TK"],
                date="2025-03-01",
                passed=True,
                dossier_numbers=["36000"],
                subject="together",
            ),
            _node(
                "wissel",
                "decision",
                ["TK"],
                date="2025-03-02",
                passed=True,
                dossier_numbers=["36000"],
                subject="wissel",
            ),
            _node(
                "roll_call",
                "decision",
                ["TK"],
                date="2025-07-01",
                passed=False,
                dossier_numbers=["36000"],
                subject="roll_call",
            ),
            _node(
                "before",
                "decision",
                ["TK"],
                date="2020-01-01",
                passed=True,
                dossier_numbers=["36000"],
                subject="before",
            ),
        ],
    )
    store.bulk_insert_or_update_edges(
        [
            *(
                make_edge_doc(
                    f"members/{m}",
                    "cabinets/schoof",
                    RELATION_SERVED_IN,
                    source="t",
                    meta={"posts": [post]},
                )
                for m, post in posts.items()
            ),
            _vote("factions/pvv", "together", "Voor", 37),
            _vote("factions/vvd", "together", "Voor", 24),
            _vote("factions/gl", "together", "Tegen", 25),
            # the PVV (the most coalition seats) against, beaten by the VVD with the
            # opposition: a wisselmeerderheid
            _vote("factions/pvv", "wissel", "Tegen", 37),
            _vote("factions/vvd", "wissel", "Voor", 24),
            _vote("factions/gl", "wissel", "Voor", 25),
            # after the PVV left: the VVD alone is the coalition; a roll call
            _vote("members/kamerlid_vvd", "roll_call", "Tegen"),
            _vote("members/kamerlid_gl", "roll_call", "Voor"),
            # no cabinet in the graph that day
            _vote("factions/gl", "before", "Voor", 20),
            # the decisions are about one dossier, as its timeline shows them
            *(
                make_edge_doc(
                    f"decisions/{key}",
                    "dossiers/36000",
                    RELATION_ABOUT,
                    source="t",
                )
                for key in ("together", "wissel", "roll_call", "before")
            ),
        ]
    )
    store.bulk_insert_or_update_nodes(
        "dossiers", [_node("36000", "dossier", number="36000", title="Begroting")]
    )


def test_what_the_coalition_did_on_each_vote(database: str, cli: Any) -> None:
    store = GraphStore()
    _seed(store)
    cli("semantic", "tk-coalition-votes")
    rows = {
        row["id"]: (row["pattern"], row["carried"], row["decisive"])
        for row in store.query("SELECT * FROM lg_decision_coalition")
    }
    assert rows == {
        "decisions/together": ("together", True, True),
        # the opposition alone (GL for) would have passed it too: not decisive
        "decisions/wissel": ("wissel", False, False),
        # the coalition (VVD) one against one: a tie is rejected, it decided it
        "decisions/roll_call": ("together", False, True),
    }

    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        wissel = client.get("/api/decisions", params={"coalition": "wissel"}).json()
        everything = client.get("/api/decisions").json()
        detail = client.get("/api/decisions/wissel").json()
        feed = client.get("/api/feed", params={"kind": "stemming"}).json()
        member_votes = client.get("/api/members/kamerlid_vvd/votes").json()
        timeline = client.get("/api/dossiers/36000/timeline").json()
        split = client.get("/api/feed", params={"coalition": "split"}).json()
        together = client.get(
            "/api/feed", params={"kind": "stemming", "coalition": "together"}
        ).json()
    finally:
        app.dependency_overrides.pop(get_store, None)

    assert [item["key"] for item in wissel["items"]] == ["wissel"]
    # the facet counts under every filter but its own
    assert {f["value"]: f["count"] for f in wissel["facets"]["coalition"]} == {
        "together": 2,
        "wissel": 1,
        "carried": 1,
        "decisive": 2,
    }
    # per cabinet, under every filter (a topic: its words, Kamer and period)
    assert everything["facets"]["coalition_cabinets"] == [
        {
            "cabinet": "schoof",
            "name": "kabinet-Schoof",
            "votes": 3,
            "together": 2,
            "split": 0,
            "wissel": 1,
            "carried": 1,
            "decisive": 2,
        }
    ]
    assert {
        i["key"]: (i["coalition"] or {}).get("pattern") for i in everything["items"]
    } == {
        "together": "together",
        "wissel": "wissel",
        "roll_call": "together",
        "before": None,
    }
    assert detail["coalition"] == {
        "cabinet": "schoof",
        "coalition_for": 24,
        "coalition_against": 37,
        "opposition_for": 25,
        "opposition_against": 0,
        "pattern": "wissel",
        "carried": False,
        "decisive": False,
    }

    # the feed gives each vote the same block and the choice of each coalition faction,
    # most seats first
    votes = {item["node"]["key"]: item["vote"] for item in feed["items"]}
    assert votes["wissel"]["coalition"] == detail["coalition"]
    assert votes["wissel"]["coalition_factions"] == [
        {
            "key": "pvv",
            "short": "PVV",
            "choice": "Tegen",
            "seats_for": 0,
            "seats_against": 37,
        },
        {
            "key": "vvd",
            "short": "VVD",
            "choice": "Voor",
            "seats_for": 24,
            "seats_against": 0,
        },
    ]
    assert [f["key"] for f in votes["roll_call"]["coalition_factions"]] == ["vvd"]
    assert votes["before"]["coalition"] is None
    assert votes["before"]["coalition_factions"] == []
    # a member's votes and a dossier's timeline give the same fields as the feed
    by_decision = {v["decision_key"]: v for v in member_votes["votes"]}
    assert by_decision["roll_call"]["coalition"] == votes["roll_call"]["coalition"]
    assert (
        by_decision["roll_call"]["coalition_factions"]
        == votes["roll_call"]["coalition_factions"]
    )
    decided = {
        e["node_id"]: e["body"]
        for e in timeline["entries"]
        if e["node_type"] == "decision"
    }
    assert decided["decisions/wissel"]["coalition"] == detail["coalition"]
    assert (
        decided["decisions/wissel"]["coalition_factions"]
        == votes["wissel"]["coalition_factions"]
    )
    assert decided["decisions/before"]["coalition"] is None
    assert decided["decisions/before"]["coalition_factions"] == []

    # a vote counts for each thing the coalition did; split holds the wisselmeerderheid
    counts = {"together": 2, "split": 1, "wissel": 1, "decisive": 2}
    assert {f["value"]: f["count"] for f in feed["facets"]["coalition"]} == counts
    assert [item["node"]["key"] for item in split["items"]] == ["wissel"]
    assert {f["value"]: f["count"] for f in split["facets"]["coalition"]} == counts
    assert [item["node"]["key"] for item in together["items"]] == [
        "roll_call",
        "together",
    ]
    assert together["total"] == 2

    # the same from the events kept apart (``feed-events``): the counts under words and
    # the periods
    cli("feed-events")
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        words = client.get(
            "/api/feed", params={"q": ["wissel", "together"], "kind": "stemming"}
        ).json()
        split_words = client.get(
            "/api/feed", params={"q": "wissel", "coalition": "split"}
        ).json()
        periods = client.get(
            "/api/feed/periods", params={"coalition": "together", "per": "month"}
        ).json()
    finally:
        app.dependency_overrides.pop(get_store, None)
    assert {f["value"]: f["count"] for f in words["facets"]["coalition"]} == {
        "together": 1,
        "split": 1,
        "wissel": 1,
        "decisive": 1,
    }
    assert split_words["total"] == 1
    assert [item["node"]["key"] for item in split_words["items"]] == ["wissel"]
    assert {p["period"]: p["total"] for p in periods["periods"]} == {
        "2025-03-01": 1,
        "2025-07-01": 1,
    }

    # a full run removes a row whose decision no longer has a coalition vote
    store.execute("DELETE FROM edges WHERE to_id = 'decisions/together'")
    cli("semantic", "tk-coalition-votes", "--since", "2025-07-01")
    assert len(list(store.query("SELECT id FROM lg_decision_coalition"))) == 3
    cli("semantic", "tk-coalition-votes")
    assert len(list(store.query("SELECT id FROM lg_decision_coalition"))) == 2
