"""``GET /api/nodes/{collection}/{key}/surroundings`` on a real graph: the submitters, the
dossier counted, the laws, the votes per faction and what follows, around one source."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.db import GraphStore
from lawgraph.db.edges import make_edge_doc
from tests.asserts import assert_status
from tests.pg.plans import recorded

DOSSIER = "dossiers/36000"
MOTION = "documents/m1"


def _node(key: str, node_type: str, **props: Any) -> dict[str, Any]:
    return {"key": key, "type": node_type, "labels": [], "props": props}


def _edge(source: str, target: str, relation: str, **fields: Any) -> dict[str, Any]:
    return make_edge_doc(source, target, relation, source="test", **fields)


@pytest.fixture()
def graph(store: GraphStore) -> GraphStore:
    """A motion m1 of dossier 36000 and its case z1, signed by a member of f1 (first) and
    one who left f2 before it; two votes on the case (one per faction, one a hamerstuk);
    the article it amends, the law it names, the law the dossier became; a letter that
    answers it and a commitment it fulfils; a loose paper l1 with nothing around it."""
    day = "2026-03-10"
    for collection, nodes in {
        "documents": [
            _node("m1", "document", date=day, title="Motie", kind="Motie"),
            _node("letter", "document", date="2026-04-01", title="Brief"),
            _node("l1", "document", date=day, title="Los stuk"),
        ],
        "cases": [_node("z1", "case", kind="Motie")],
        "dossiers": [_node("36000", "dossier", number="36000")],
        "members": [_node(k, "member", name=k) for k in ("a", "b", "c")],
        "factions": [_node(k, "faction", name=k) for k in ("f1", "f2")],
        "decisions": [
            _node("b1", "decision", date=day, tally={"Voor": 15, "Tegen": 10}),
            _node("b2", "decision", date="2026-03-01", vote_kind="faction"),
        ],
        "articles": [_node("a1", "article", bwb_id="BWBR1", article_number="1")],
        "instruments": [
            _node("law", "instrument", bwb_id="BWBR1"),
            _node("wet2", "instrument", bwb_id="BWBR2"),
        ],
        "commitments": [_node("tz1", "commitment", text="Een brief.")],
        "activities": [_node("act1", "activity", date=day)],
        "committees": [_node("c1", "committee", name="Commissie")],
    }.items():
        store.bulk_insert_or_update_nodes(collection, nodes)
    store.bulk_insert_or_update_edges(
        [
            _edge(MOTION, "cases/z1", "PART_OF"),
            _edge(MOTION, DOSSIER, "PART_OF"),
            _edge("cases/z1", DOSSIER, "PART_OF"),
            _edge("documents/letter", DOSSIER, "PART_OF"),
            _edge("cases/z1", "committees/c1", "LED_BY"),
            _edge(MOTION, "activities/act1", "MADE_IN"),
            _edge("members/a", MOTION, "AUTHORED", meta={"role": "Mede ondertekenaar"}),
            _edge(
                "members/b",
                MOTION,
                "AUTHORED",
                meta={"role": "Eerste ondertekenaar", "capacity": "kamerlid"},
            ),
            _edge(
                "members/c",
                MOTION,
                "AUTHORED",
                meta={"role": "Mede ondertekenaar", "capacity": "kamerlid"},
            ),
            _edge(
                "members/b",
                "factions/f1",
                "MEMBER_OF",
                meta={"from_date": "2020-01-01", "to_date": None},
            ),
            _edge(
                "members/c",
                "factions/f2",
                "MEMBER_OF",
                meta={"from_date": "2020-01-01", "to_date": "2026-01-01"},
            ),
            _edge("decisions/b1", "cases/z1", "ABOUT"),
            _edge("decisions/b2", MOTION, "ABOUT"),
            _edge("decisions/b1", DOSSIER, "ABOUT"),
            _edge("decisions/b2", DOSSIER, "ABOUT"),
            _edge(
                "factions/f1",
                "decisions/b1",
                "VOTED",
                meta={"choice": "Voor", "seats": 15},
            ),
            _edge(
                "factions/f2",
                "decisions/b1",
                "VOTED",
                meta={"choice": "Tegen", "seats": 10},
            ),
            _edge(MOTION, "articles/a1", "AMENDS", status="voorgesteld"),
            _edge(MOTION, "instruments/law", "REFERS_TO"),
            _edge("instruments/wet2", DOSSIER, "LEGISLATED_IN"),
            _edge(MOTION, "commitments/tz1", "ANSWERS"),
            _edge("documents/letter", MOTION, "ANSWERS"),
        ]
    )
    store.vacuum_analyze()
    return store


@pytest.fixture()
def client(graph: GraphStore) -> Iterator[TestClient]:
    app.dependency_overrides[get_store] = lambda: graph
    yield TestClient(app)
    app.dependency_overrides.pop(get_store, None)


def _get(client: TestClient, path: str, status: int = 200) -> dict[str, Any]:
    response = client.get(f"/api/nodes/{path}/surroundings")
    assert_status(response, status)
    body: dict[str, Any] = response.json()
    return body


def _ids(items: list[dict[str, Any]]) -> list[str]:
    return [i["node"]["id"] for i in items]


def test_a_motion_has_its_submitters_with_the_faction_of_that_day(
    client: TestClient,
) -> None:
    body = _get(client, MOTION)

    assert body["focal"]["id"] == MOTION
    assert [s["node"]["id"] for s in body["submitters"]] == [
        "members/b",
        "members/a",
        "members/c",
    ]
    factions = {s["node"]["id"]: s["faction"] for s in body["submitters"]}
    assert factions["members/b"]["id"] == "factions/f1"
    assert factions["members/a"] is None  # no membership recorded
    assert factions["members/c"] is None  # left f2 before the day
    assert body["submitters_total"] == 3
    assert body["submitters"][0]["role"] == "Eerste ondertekenaar"


def test_the_dossier_is_one_node_with_what_it_holds_counted(client: TestClient) -> None:
    body = _get(client, MOTION)

    (dossier,) = body["dossiers"]
    assert dossier["node"]["id"] == DOSSIER
    assert dossier["held"] == {
        "documents": 2,
        "cases": 1,
        "decisions": 2,
        "commitments": 0,
        "activities": 0,
        "laws": 1,
    }
    assert body["dossiers_total"] == 1


def test_the_laws_come_by_what_the_paper_does_to_them(client: TestClient) -> None:
    body = _get(client, MOTION)

    laws = body["laws"]
    assert [(i["node"]["id"], i["relation"], i["status"]) for i in laws["items"]] == [
        ("articles/a1", "AMENDS", "voorgesteld"),
        ("instruments/wet2", "LEGISLATED_IN", "canoniek"),
        ("instruments/law", "REFERS_TO", "canoniek"),
    ]
    assert laws["items"][1]["direction"] == "inbound"
    assert laws["total"] == 3


def test_the_votes_on_the_paper_and_its_case_have_the_vote_per_faction(
    client: TestClient,
) -> None:
    body = _get(client, MOTION)

    assert body["votes_total"] == 2
    first, second = body["votes"]
    assert (first["node"]["id"], first["about"]) == ("decisions/b1", "cases/z1")
    assert [
        (f["faction"]["id"], f["choice"], f["seats"]) for f in first["factions"]
    ] == [("factions/f1", "Voor", 15), ("factions/f2", "Tegen", 10)]
    assert (second["node"]["id"], second["factions"]) == ("decisions/b2", [])
    assert [g["reason"] for g in body["gaps"] if g["section"] == "votes"] == [
        "No vote per faction is recorded for 1 of the 2 decisions shown "
        "(a hamerstuk, a roll call, or a vote not yet read)."
    ]


def test_what_follows_and_where_it_was_made(client: TestClient) -> None:
    body = _get(client, MOTION)

    assert [
        (i["node"]["id"], i["relation"], i["direction"])
        for i in body["follows"]["items"]
    ] == [
        ("commitments/tz1", "ANSWERS", "outbound"),
        ("documents/letter", "ANSWERS", "inbound"),
    ]
    assert sorted(_ids(body["context"]["items"])) == [
        "activities/act1",
        "committees/c1",
    ]


def test_a_vote_has_the_paper_it_is_on_its_dossier_and_its_factions(
    client: TestClient,
) -> None:
    body = _get(client, "decisions/b1")

    assert body["votes_total"] == 1
    (vote,) = body["votes"]
    assert vote["node"]["id"] == "decisions/b1" and len(vote["factions"]) == 2
    assert _ids([{"node": d["node"]} for d in body["dossiers"]]) == [DOSSIER]
    assert [s["node"]["id"] for s in body["submitters"]] == []  # a case has none here


def test_a_commitment_and_an_activity_have_their_own_surroundings(
    client: TestClient,
) -> None:
    commitment = _get(client, "commitments/tz1")
    activity = _get(client, "activities/act1")

    assert [i["node"]["id"] for i in commitment["follows"]["items"]] == [MOTION]
    assert [i["node"]["id"] for i in activity["follows"]["items"]] == [MOTION]
    assert [g for g in commitment["gaps"] if g["section"] == "votes"] == []


def test_a_paper_with_nothing_around_it_says_what_is_missing(
    client: TestClient,
) -> None:
    body = _get(client, "documents/l1")

    assert body["submitters"] == [] and body["dossiers"] == [] and body["votes"] == []
    assert body["laws"]["total"] == 0
    assert {g["section"] for g in body["gaps"]} == {
        "submitters",
        "dossiers",
        "laws",
        "votes",
    }


def test_cap_cuts_a_section_but_not_its_total(client: TestClient) -> None:
    response = client.get(f"/api/nodes/{MOTION}/surroundings?cap=1")
    assert_status(response, 200)
    body = response.json()

    assert len(body["submitters"]) == 1 and body["submitters_total"] == 3
    assert len(body["laws"]["items"]) == 1 and body["laws"]["total"] == 3
    assert len(body["votes"]) == 1 and body["votes_total"] == 2


def test_another_collection_is_422_and_a_missing_node_404(client: TestClient) -> None:
    assert_status(client.get("/api/nodes/articles/a1/surroundings"), 422)
    assert_status(client.get("/api/nodes/documents/nope/surroundings"), 404)


def test_it_reads_a_few_statements(
    graph: GraphStore, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = recorded(graph, monkeypatch)

    _get(client, MOTION)

    assert len(calls) <= 40
