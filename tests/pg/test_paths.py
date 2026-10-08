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


def test_a_level_reads_the_edges_of_a_hub_from_the_index_alone(
    store: GraphStore,
) -> None:
    """A level of a hub (an article 20,000 judgments cite) reads both ends, the relation and
    the key of its edges from a covering index, not a page of the table per edge (cold
    seconds on the full graph)."""
    import json

    from lawgraph.db.store import _query

    hub = "articles/hub"
    store.bulk_insert_or_update_nodes(
        "articles", [{"_key": "hub", "type": "article", "labels": [], "props": {}}]
    )
    store.bulk_insert_or_update_edges(
        [_edge(f"r{n}", f"judgments/j{n}", hub, "REFERS_TO") for n in range(3000)]
    )
    # the edges of the rest of the graph, of which those of the hub are a small part
    store.bulk_insert_or_update_edges(
        [
            _edge(f"o{n}", f"judgments/k{n}", f"articles/a{n % 3000}", "REFERS_TO")
            for n in range(30_000)
        ]
    )
    store.vacuum_analyze()
    levels: list[tuple[Any, Any]] = []
    query = store.query

    def recording(statement: Any, params: Any = None, **options: Any) -> Any:
        if params and "frontier" in params:
            # read in index order, never a node's edges whole and sorted
            assert options.get("index_order"), options
            levels.append((statement, params))
        return query(statement, params, **options)

    store.query = recording  # type: ignore[method-assign]
    try:
        get_paths(store, [hub, "articles/elsewhere"], max_depth=2)
    finally:
        store.query = query  # type: ignore[method-assign]
    statement, params = next((s, p) for s, p in levels if p["frontier"] == [hub])
    with store.pool.connection() as conn:
        conn.execute("SET LOCAL enable_bitmapscan = off")  # as ``index_order``
        explain = b"EXPLAIN (FORMAT JSON) " + _query(statement).as_bytes(conn)
        plan = json.dumps(conn.execute(explain, params).fetchone()[0])
    assert "Index Only Scan" in plan and "edges_to_cover" in plan, plan


# ── groups joined through their children (expand=members) ────────────────────

VVD = "factions/vvd"
SR = "instruments/sr"
MINISTER = "members/dy"


def _groups(store: GraphStore) -> None:
    """A faction whose own edges are its votes (more than a level keeps), a minister who
    is one of its members and signed a bill that changes an article of a law, and that
    law with its articles."""
    nodes: dict[str, list[dict[str, Any]]] = {
        "factions": [_node("vvd", "faction", name="VVD")],
        "members": [
            _node("dy", "member", name="D. Y."),
            _node("old", "member", name="O."),
        ],
        "instruments": [_node("sr", "instrument", title="Wetboek van Strafrecht")],
        "articles": [
            _node(f"sr_{n}", "article", inbound_citation_count=n) for n in range(1, 6)
        ],
        "documents": [_node("bill", "document", title="Wetsvoorstel")],
        "decisions": [_node(f"v{n:03d}", "decision") for n in range(30)],
    }
    for collection, docs in nodes.items():
        store.bulk_insert_or_update_nodes(collection, docs)
    seated = {**_edge("m1", MINISTER, VVD, "MEMBER_OF"), "meta": {"from_date": "2015"}}
    gone = {
        **_edge("m2", "members/old", VVD, "MEMBER_OF"),
        "meta": {"from_date": "2000", "to_date": "2010-01-01"},
    }
    store.bulk_insert_or_update_edges(
        [
            seated,
            gone,
            *(_edge(f"p{n}", f"articles/sr_{n}", SR, "PART_OF") for n in range(1, 6)),
            _edge("a1", MINISTER, "documents/bill", "AUTHORED"),
            _edge("x1", "documents/bill", "articles/sr_2", "AMENDS"),
            *(
                _edge(f"vote{n:03d}", VVD, f"decisions/v{n:03d}", "VOTED")
                for n in range(30)
            ),
        ]
    )


def test_groups_are_joined_through_their_children(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VVD, Sr and a minister of the VVD: without ``expand`` the faction meets the law
    nowhere (its own edges are its votes, cut at a level); with it the faction is its
    members and the law its articles: VVD ∋ minister → bill → art. ∈ Sr."""
    _groups(store)
    monkeypatch.setattr(paths_queries, "LEVEL_CAP", 10)
    ids = [VVD, SR, MINISTER]
    plain = get_paths(store, ids, max_depth=2)
    assert (VVD, SR) not in {(p.source, p.target) for p in plain["paths"]}

    found = get_paths(store, ids, max_depth=2, expand_cap=200)
    paths = {(p.source, p.target): p for p in found["paths"]}
    across = paths[(VVD, SR)]
    assert across.nodes == (
        VVD,
        MINISTER,
        "documents/bill",
        "articles/sr_2",
        SR,
    )
    assert set(across.edges) & found["membership"] == {"m1", "p2"}
    # a member of the group is joined to it by its membership alone
    assert paths[(VVD, MINISTER)].edges == ("m1",)
    assert found["expanded"] == {
        VVD: {"used": 2, "total": 2},
        SR: {"used": 5, "total": 5},
    }
    assert found["partial"] is False


def test_a_group_starts_from_its_most_telling_children(store: GraphStore) -> None:
    """Of a faction those seated first, of a law its most cited articles; of a dossier its
    own papers before those of its cases, and a paper of a case only with its case."""
    from lawgraph.db.queries.path_groups import children_of

    _groups(store)
    assert [c.id for c in children_of(store, VVD, 1).kept] == [MINISTER]
    assert [c.id for c in children_of(store, SR, 2).kept] == [
        "articles/sr_5",
        "articles/sr_4",
    ]

    store.bulk_insert_or_update_nodes("dossiers", [_node("36547", "dossier")])
    store.bulk_insert_or_update_nodes("cases", [_node("c1", "case")])
    store.bulk_insert_or_update_nodes(
        "documents",
        [
            _node("own_old", "document", date="2020-01-01"),
            _node("own_new", "document", date="2024-01-01"),
            _node("of_case", "document", date="2025-01-01"),
        ],
    )
    store.bulk_insert_or_update_edges(
        [
            _edge("d1", "documents/own_old", "dossiers/36547", "PART_OF"),
            _edge("d2", "documents/own_new", "dossiers/36547", "PART_OF"),
            _edge("d3", "cases/c1", "dossiers/36547", "PART_OF"),
            _edge("d4", "documents/of_case", "cases/c1", "PART_OF"),
        ]
    )
    dossier = children_of(store, "dossiers/36547", 10)
    assert [c.id for c in dossier.kept] == [
        "documents/own_new",
        "documents/own_old",
        "cases/c1",
        "documents/of_case",
    ]
    assert dossier.kept[-1].parent == "cases/c1" and dossier.total == 4
    assert [c.id for c in children_of(store, "dossiers/36547", 2).kept] == [
        "documents/own_new",
        "documents/own_old",
    ]


def test_a_search_past_its_time_answers_what_it_found(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The search of groups may read much: past ``PATHS_BUDGET`` the paths found by then,
    ``partial``, never a 503."""
    _groups(store)
    monkeypatch.setattr(paths_queries, "PATHS_BUDGET", 0.0)
    found = get_paths(store, [VVD, SR, MINISTER], max_depth=4, expand_cap=200)
    assert found["partial"] is True


def test_the_route_joins_groups_through_their_children(store: GraphStore) -> None:
    _groups(store)
    app.dependency_overrides[get_store] = lambda: store
    try:
        body = (
            TestClient(app)
            .get(
                "/api/paths",
                params={"ids": f"{VVD},{SR}", "max_depth": 2, "expand": "members"},
            )
            .json()
        )
    finally:
        app.dependency_overrides.pop(get_store, None)
    (path,) = body["paths"]
    assert path["via"] == {VVD: MINISTER, SR: "articles/sr_2"}
    assert path["membership_edge_ids"] == ["edges/m1", "edges/p2"]
    assert body["expanded"] == {
        VVD: {"used": 2, "total": 2},
        SR: {"used": 5, "total": 5},
    }
    assert body["expand"] == "members" and body["partial"] is False


def test_two_groups_read_a_level_of_their_children_from_the_index(
    store: GraphStore,
) -> None:
    """Two groups facing each other: a level of hundreds of children is read from the
    covering indexes alone, not a page of the table per edge."""
    import json

    from lawgraph.db.store import _query

    store.bulk_insert_or_update_nodes("factions", [_node("big", "faction")])
    store.bulk_insert_or_update_nodes("instruments", [_node("law", "instrument")])
    store.bulk_insert_or_update_edges(
        [
            _edge(f"m{n}", f"members/p{n}", "factions/big", "MEMBER_OF")
            for n in range(300)
        ]
        + [
            _edge(f"p{n}", f"articles/a{n}", "instruments/law", "PART_OF")
            for n in range(300)
        ]
        + [
            _edge(f"o{n}", f"documents/d{n}", f"articles/x{n % 3000}", "REFERS_TO")
            for n in range(30_000)
        ]
    )
    store.vacuum_analyze()
    levels: list[tuple[Any, Any]] = []
    query = store.query

    def recording(statement: Any, params: Any = None, **options: Any) -> Any:
        if params and len(params.get("frontier") or []) > 100:
            # read in index order, never a node's edges whole and sorted
            assert options.get("index_order"), options
            levels.append((statement, params))
        return query(statement, params, **options)

    store.query = recording  # type: ignore[method-assign]
    try:
        get_paths(store, ["factions/big", "instruments/law"], 2, expand_cap=500)
    finally:
        store.query = query  # type: ignore[method-assign]
    assert levels
    statement, params = levels[0]
    with store.pool.connection() as conn:
        conn.execute("SET LOCAL enable_bitmapscan = off")  # as ``index_order``
        explain = b"EXPLAIN (FORMAT JSON) " + _query(statement).as_bytes(conn)
        plan = json.dumps(conn.execute(explain, params).fetchone()[0])
    assert plan.count("Index Only Scan") == 2, plan
    assert "edges_from_cover" in plan and "edges_to_cover" in plan


def test_a_level_reads_a_share_of_each_node_not_a_hub_whole(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A level of the children of a law of which one is a hub (an article 20,000 papers
    cite) reads a share of the level per child in index order, not every edge of the hub
    to keep the lowest ids (Sr: 689,000 citations read for a level of 100,000); every child
    reaches the level."""
    from lawgraph.db.store import _query

    monkeypatch.setattr(paths_queries, "_ROWS_PER_LEVEL", 3000)
    store.bulk_insert_or_update_nodes("instruments", [_node("law", "instrument")])
    store.bulk_insert_or_update_nodes("factions", [_node("big", "faction")])
    store.bulk_insert_or_update_edges(
        [
            _edge(f"p{n}", f"articles/a{n}", "instruments/law", "PART_OF")
            for n in range(300)
        ]
        + [
            _edge(f"h{n}", f"documents/h{n}", "articles/a0", "REFERS_TO")
            for n in range(20_000)
        ]
        + [
            _edge(f"c{n}", f"documents/c{n}", f"articles/a{n % 300}", "REFERS_TO")
            for n in range(1, 600)
        ]
        + [
            _edge(f"m{n}", f"members/p{n}", "factions/big", "MEMBER_OF")
            for n in range(400)
        ]
    )
    store.vacuum_analyze()
    levels: list[tuple[Any, Any]] = []
    query = store.query

    def recording(statement: Any, params: Any = None, **options: Any) -> Any:
        if params and len(params.get("frontier") or []) > 100:
            # read in index order, never a node's edges whole and sorted
            assert options.get("index_order"), options
            levels.append((statement, params))
        return query(statement, params, **options)

    store.query = recording  # type: ignore[method-assign]
    try:
        # a faction of more members on the other side: the law's side reads the level
        get_paths(store, ["instruments/law", "factions/big"], 2, expand_cap=500)
    finally:
        store.query = query  # type: ignore[method-assign]
    statement, params = levels[0]
    assert len(params["frontier"]) == 301  # the law and its 300 articles
    with store.pool.connection() as conn:
        conn.execute("SET LOCAL enable_bitmapscan = off")  # as ``index_order``
        explain = b"EXPLAIN (ANALYZE, FORMAT JSON) " + _query(statement).as_bytes(conn)
        plan = conn.execute(explain, params).fetchone()[0]

    def scans(node: dict[str, Any]) -> Any:
        yield node
        for child in node.get("Plans", []):
            yield from scans(child)

    edges = [n for n in scans(plan[0]["Plan"]) if n.get("Relation Name") == "edges"]
    read = sum(
        (n["Actual Rows"] + n.get("Rows Removed by Filter", 0)) * n["Actual Loops"]
        for n in edges
    )
    # a share each way per child: at most twice the level, not the hub's 20,000
    assert read <= 2 * 3000, read
    assert all(n["Node Type"] == "Index Only Scan" for n in edges), [
        (n["Node Type"], n.get("Index Name")) for n in edges
    ]
    assert params["share"] == 10
    rows = list(store.query(statement, params))
    assert {r["node"] for r in rows} >= {f"articles/a{n}" for n in range(300)}
