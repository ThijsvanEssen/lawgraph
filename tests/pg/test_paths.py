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
from lawgraph.db.queries.paths import get_paths

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
