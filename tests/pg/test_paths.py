"""``GET /api/paths`` on a real PostgreSQL: the shortest path between chosen nodes (BE-38)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.db import GraphStore
from lawgraph.db.queries import paths as paths_queries
from lawgraph.db.queries.paths import Followed, get_paths

MEMBER = "members/m"
ARTICLE = "articles/awb_3_7"


def _node(key: str, kind: str, **props: Any) -> dict[str, Any]:
    return {"_key": key, "type": kind, "labels": [], "props": props}


def _edge(key: str, source: str, target: str, relation: str) -> dict[str, Any]:
    return {
        "_key": key,
        "_from": source,
        "_to": target,
        "relation": relation,
        "source": "test",
        "status": "canoniek",
        "confidence": 1.0,
        "meta": {},
    }


@pytest.fixture()
def graph(store: GraphStore) -> GraphStore:
    """A member signed a paper of dossier 33328; the law of that dossier amends art. 3:7
    Awb: four edges, followed in either direction."""
    store.bulk_insert_or_update_nodes("members", [_node("m", "member", name="A. Lid")])
    store.bulk_insert_or_update_nodes(
        "documents",
        [_node("d1", "document", title="Brief"), _node("d2", "document", title="Nota")],
    )
    store.bulk_insert_or_update_nodes("dossiers", [_node("33328", "dossier")])
    store.bulk_insert_or_update_nodes("instruments", [_node("stb", "instrument")])
    store.bulk_insert_or_update_nodes("articles", [_node("awb_3_7", "article")])
    store.bulk_insert_or_update_edges(
        [
            _edge("e1", MEMBER, "documents/d1", "AUTHORED"),
            # a second way of the same length, through a higher id
            _edge("e1b", MEMBER, "documents/d2", "AUTHORED"),
            _edge("e2", "documents/d1", "dossiers/33328", "PART_OF"),
            _edge("e2b", "documents/d2", "dossiers/33328", "PART_OF"),
            _edge("e3", "instruments/stb", "dossiers/33328", "LEGISLATED_IN"),
            _edge("e4", "instruments/stb", ARTICLE, "AMENDS"),
        ]
    )
    return store


def test_the_shortest_path_through_the_lowest_ids(graph: GraphStore) -> None:
    found = get_paths(graph, [MEMBER, ARTICLE], max_depth=4)
    (path,) = found["paths"]
    assert path.nodes == (
        MEMBER,
        "documents/d1",
        "dossiers/33328",
        "instruments/stb",
        ARTICLE,
    )
    assert path.edges == ("e1", "e2", "e3", "e4")
    assert [n["_id"] for n in found["nodes"]] == sorted(path.nodes)
    assert [e["_key"] for e in found["edges"]] == ["e1", "e2", "e3", "e4"]
    assert found["capped"] is False


def test_no_path_beyond_max_depth_and_every_pair(graph: GraphStore) -> None:
    assert get_paths(graph, [MEMBER, ARTICLE], max_depth=3)["paths"] == []
    three = get_paths(graph, [MEMBER, "dossiers/33328", ARTICLE], max_depth=4)
    assert [(p.source, p.target, len(p.edges)) for p in three["paths"]] == [
        (MEMBER, "dossiers/33328", 2),
        (MEMBER, ARTICLE, 4),
        ("dossiers/33328", ARTICLE, 2),
    ]


def test_a_level_cut_at_the_cap_says_so(
    graph: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(paths_queries, "LEVEL_CAP", 1)
    found = get_paths(graph, [MEMBER, ARTICLE], max_depth=4)
    # at the dossier the level keeps documents/d2 (the lowest id) and not the law: the
    # path is missed, and the answer says a level was cut
    assert (found["paths"], found["capped"]) == ([], True)
    assert get_paths(graph, [MEMBER, "dossiers/33328"], max_depth=4)["paths"]


def _law_and_explanation(store: GraphStore) -> None:
    """The graph of Schouw and Voortman and art. 3:7 Awb (BE-49): the bill's memorie
    cites the Awb, and explains a version of the article; the law of the bill amends it."""
    store.bulk_insert_or_update_nodes("instruments", [_node("awb", "instrument")])
    store.bulk_insert_or_update_nodes(
        "article_versions", [_node("av_3_7", "article_version")]
    )
    store.bulk_insert_or_update_edges(
        [
            _edge("w1", "documents/d1", "instruments/awb", "REFERS_TO"),
            _edge("w2", ARTICLE, "instruments/awb", "PART_OF"),
            _edge("w3", "documents/d1", "article_versions/av_3_7", "EXPLAINS"),
            _edge("w4", "article_versions/av_3_7", ARTICLE, "VERSION_OF"),
        ]
    )


def test_a_path_does_not_pass_through_a_law_by_its_articles(graph: GraphStore) -> None:
    _law_and_explanation(graph)
    # the memorie explains a version of the article: three steps, through no law
    (path,) = get_paths(graph, [MEMBER, ARTICLE], max_depth=4)["paths"]
    assert path.nodes == (MEMBER, "documents/d1", "article_versions/av_3_7", ARTICLE)
    # through the law it cites, when asked: the article is part of it
    cites = Followed(relations=["AUTHORED", "REFERS_TO", "PART_OF"], through_laws=True)
    (through,) = get_paths(graph, [MEMBER, ARTICLE], max_depth=4, followed=cites)[
        "paths"
    ]
    assert through.nodes == (MEMBER, "documents/d1", "instruments/awb", ARTICLE)
    blocked = Followed(relations=["AUTHORED", "REFERS_TO", "PART_OF"])
    assert get_paths(graph, [MEMBER, ARTICLE], 4, blocked)["paths"] == []
    # a law that is one of the pair is reached by its articles
    (own,) = get_paths(graph, [ARTICLE, "instruments/awb"], max_depth=1)["paths"]
    assert own.edges == ("w2",)


def test_a_law_an_end_of_another_pair_is_not_passed_through(graph: GraphStore) -> None:
    """The levels are read once for every pair, with every id as an end; a pair still does
    not pass through a law that is an end of another pair only."""
    _law_and_explanation(graph)
    blocked = Followed(relations=["AUTHORED", "REFERS_TO", "PART_OF"])
    found = get_paths(graph, [MEMBER, ARTICLE, "instruments/awb"], 4, blocked)
    assert [(p.source, p.target, p.edges) for p in found["paths"]] == [
        (MEMBER, "instruments/awb", ("e1", "w1")),
        (ARTICLE, "instruments/awb", ("w2",)),
    ]


def test_every_level_is_read_once_for_every_pair(graph: GraphStore) -> None:
    """Four ids are six pairs; the edges at a frontier are read once, whichever pairs
    reach it."""
    _law_and_explanation(graph)
    frontiers: list[tuple[str, ...]] = []
    query = graph.query

    def recording(statement: Any, params: Any = None, **options: Any) -> Any:
        if params and "frontier" in params:
            frontiers.append(tuple(params["frontier"]))
        return query(statement, params, **options)

    graph.query = recording  # type: ignore[method-assign]
    try:
        found = get_paths(
            graph, [MEMBER, ARTICLE, "dossiers/33328", "instruments/awb"], max_depth=4
        )
    finally:
        graph.query = query  # type: ignore[method-assign]
    assert len(found["paths"]) == 6
    assert len(frontiers) == len(set(frontiers))


def test_the_relations_a_path_keeps_to(graph: GraphStore) -> None:
    _law_and_explanation(graph)
    bill = Followed(
        relations=["AUTHORED", "PART_OF", "LEGISLATED_IN", "AMENDS", "INTRODUCES"]
    )
    # the bill's way: member, paper, dossier 33328, the law it made, the change
    (path,) = get_paths(graph, [MEMBER, ARTICLE], max_depth=4, followed=bill)["paths"]
    assert path.nodes == (
        MEMBER,
        "documents/d1",
        "dossiers/33328",
        "instruments/stb",
        ARTICLE,
    )
    assert path.edges == ("e1", "e2", "e3", "e4")
    without = Followed(relations=["PART_OF", "LEGISLATED_IN", "AMENDS"])
    assert get_paths(graph, [MEMBER, ARTICLE], 4, without)["paths"] == []


@pytest.fixture()
def client(graph: GraphStore) -> Iterator[TestClient]:
    app.dependency_overrides[get_store] = lambda: graph
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_store, None)


def test_the_route(client: TestClient) -> None:
    body = client.get(
        "/api/paths", params={"ids": f"{MEMBER},{ARTICLE}", "max_depth": 4}
    ).json()
    assert body["ids"] == [MEMBER, ARTICLE] and body["max_depth"] == 4
    (path,) = body["paths"]
    assert path["length"] == 4 and path["edge_ids"][0] == "edges/e1"
    assert {n["id"] for n in body["nodes"]} == set(path["node_ids"])
    assert [e["relation"] for e in body["edges"]] == [
        "AUTHORED",
        "PART_OF",
        "LEGISLATED_IN",
        "AMENDS",
    ]
    assert client.get("/api/paths", params={"ids": MEMBER}).status_code == 422
    assert client.get("/api/paths", params={"ids": "x,y"}).status_code == 422
    assert (
        client.get("/api/paths", params={"ids": f"{MEMBER},articles/none"}).status_code
        == 404
    )


def test_the_route_takes_relations_and_through_laws(client: TestClient) -> None:
    ids = f"{MEMBER},{ARTICLE}"
    body = client.get(
        "/api/paths", params={"ids": ids, "relations": "AUTHORED,PART_OF"}
    ).json()
    assert (body["relations"], body["through_laws"], body["paths"]) == (
        ["AUTHORED", "PART_OF"],
        False,
        [],
    )
    body = client.get("/api/paths", params={"ids": ids, "through_laws": "true"}).json()
    assert (body["relations"], body["through_laws"]) == (None, True)
    assert body["paths"][0]["length"] == 4
    wrong = client.get("/api/paths", params={"ids": ids, "relations": "NOPE"})
    assert wrong.status_code == 422
