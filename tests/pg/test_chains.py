"""``GET /api/chains`` on a real graph: chains of one to six steps between two nodes, searched on
the steps ``semantic graph-steps`` builds."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_DOCUMENTS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    RELATION_PART_OF,
    RELATION_REFERS_TO,
)
from lawgraph.core.models import NodeType
from lawgraph.db import GraphStore
from lawgraph.db.edges import make_edge_doc
from lawgraph.db.queries import chains as chains_queries
from lawgraph.db.queries.chains import get_chains
from lawgraph.db.queries.source_steps import build_source_steps
from tests.asserts import assert_status

WATER, HOUSING, BOOK7, MUNI, AWB = (
    f"{COLLECTION_INSTRUMENTS}/{key}" for key in ("ws", "ww", "bw7", "gw", "awb")
)
MVT, OTHER, LETTER, BOTH = (
    f"{COLLECTION_DOCUMENTS}/{key}" for key in ("35133-3", "36496-3", "36000-1", "x-1")
)
ART_1, ART_2 = (f"{COLLECTION_ARTICLES}/{key}" for key in ("awb_1", "awb_2"))
RULING = f"{COLLECTION_JUDGMENTS}/j1"


def _node(node_type: NodeType, key: str, **props: Any) -> dict[str, Any]:
    return {"key": key, "type": node_type.value, "labels": [], "props": props}


def _edge(
    source: str, target: str, relation: str = RELATION_REFERS_TO
) -> dict[str, Any]:
    return make_edge_doc(source, target, relation, source="test")


def _articles(store: GraphStore, *keys: str) -> list[str]:
    store.bulk_insert_or_update_nodes(
        COLLECTION_ARTICLES, [_node(NodeType.ARTICLE, key) for key in keys]
    )
    return [f"{COLLECTION_ARTICLES}/{key}" for key in keys]


def _papers(store: GraphStore, names: dict[str, list[str]]) -> None:
    """Each paper names its sources."""
    store.bulk_insert_or_update_nodes(
        COLLECTION_DOCUMENTS, [_node(NodeType.DOCUMENT, key) for key in names]
    )
    store.bulk_insert_or_update_edges(
        [
            _edge(f"{COLLECTION_DOCUMENTS}/{key}", source)
            for key, sources in names.items()
            for source in sources
        ]
    )
    build_source_steps(store)


@pytest.fixture()
def graph(store: GraphStore) -> GraphStore:
    """The memorie 35133, nr. 3 names the Waterschapswet and the Woningwet; 36496, nr. 3
    the Woningwet and Boek 7: two steps from the Waterschapswet to Boek 7. The Gemeentewet
    refers to the Awb, two articles of the Awb refer to each other, a judgment cites the
    second and the Woningwet: three steps from the Gemeentewet to the Woningwet."""
    store.bulk_insert_or_update_nodes(
        COLLECTION_INSTRUMENTS,
        [_node(NodeType.INSTRUMENT, key) for key in ("ws", "ww", "bw7", "gw", "awb")],
    )
    _articles(store, "awb_1", "awb_2")
    store.bulk_insert_or_update_nodes(
        COLLECTION_DOCUMENTS,
        [
            _node(NodeType.DOCUMENT, key, title="Memorie van toelichting")
            for key in ("35133-3", "36496-3", "36000-1", "x-1")
        ],
    )
    store.bulk_insert_or_update_nodes(
        COLLECTION_JUDGMENTS,
        [_node(NodeType.JUDGMENT, "j1", ecli="ECLI:NL:HR:2020:1")],
    )
    store.bulk_insert_or_update_edges(
        [
            _edge(MVT, WATER),
            _edge(MVT, HOUSING),
            _edge(OTHER, HOUSING),
            _edge(OTHER, BOOK7),
            _edge(BOTH, MUNI),
            _edge(BOTH, AWB),
            _edge(MUNI, AWB),
            _edge(ART_1, AWB, RELATION_PART_OF),
            _edge(ART_2, AWB, RELATION_PART_OF),
            _edge(LETTER, MUNI),
            _edge(LETTER, ART_1),
            _edge(ART_1, ART_2),
            _edge(RULING, ART_2),
            _edge(RULING, HOUSING),
        ]
    )
    build_source_steps(store)
    return store


@pytest.fixture()
def client(graph: GraphStore) -> Iterator[TestClient]:
    app.dependency_overrides[get_store] = lambda: graph
    yield TestClient(app)
    app.dependency_overrides.pop(get_store, None)


def _get(client: TestClient, query: str) -> dict[str, Any]:
    response = client.get(f"/api/chains?{query}")
    assert_status(response, 200)
    body: dict[str, Any] = response.json()
    return body


def test_two_steps_through_a_law_each_named_with_another(client: TestClient) -> None:
    body = _get(client, f"ids={WATER},{BOOK7}")

    one, two = body["blocks"]
    assert (one["steps"], one["total"], one["chains"], one["complete"]) == (
        1,
        0,
        [],
        True,
    )
    (chain,) = two["chains"]
    assert chain["node_ids"] == [WATER, HOUSING, BOOK7]
    assert [
        (s["source"], s["via"], s["target"], s["ways"]) for s in chain["steps"]
    ] == [
        (WATER, MVT, HOUSING, 1),
        (HOUSING, OTHER, BOOK7, 1),
    ]
    # a paper that names two sources alone: 1 / ln 2 each step
    assert [round(s["weight"], 3) for s in chain["steps"]] == [1.443, 1.443]
    assert round(chain["weight"], 3) == 1.443
    edges = {e["id"]: e for e in body["edges"]}
    # the edges of a step from its source: the paper names both
    first = [edges[e] for e in chain["steps"][0]["edge_ids"]]
    assert [(e["source"], e["target"], e["relation"]) for e in first] == [
        (MVT, WATER, "REFERS_TO"),
        (MVT, HOUSING, "REFERS_TO"),
    ]
    assert sorted(n["id"] for n in body["nodes"]) == sorted(
        [WATER, HOUSING, BOOK7, MVT, OTHER]
    )


def test_one_step_is_an_edge_or_what_both_share(client: TestClient) -> None:
    body = _get(client, f"ids={MUNI},{AWB}&max_steps=1")

    (one,) = body["blocks"]
    (chain,) = one["chains"]
    assert chain["node_ids"] == [MUNI, AWB]
    # the edge between them before the paper that names both
    (step,) = chain["steps"]
    assert (step["via"], step["ways"]) == (None, 2)
    assert one["total"] == 1


def test_three_steps_and_no_law_passed_by_its_articles(client: TestClient) -> None:
    body = _get(client, f"ids={MUNI},{HOUSING}&max_steps=3")

    one, two, three = body["blocks"]
    assert (one["total"], two["total"]) == (0, 0)
    # the Gemeentewet and art. 2 Awb: no step through the Awb by its articles
    assert [c["node_ids"] for c in three["chains"]] == [[MUNI, ART_1, ART_2, HOUSING]]
    (chain,) = three["chains"]
    assert [(s["via"], s["ways"]) for s in chain["steps"]] == [
        (LETTER, 1),
        (None, 1),
        (RULING, 1),
    ]
    assert three["total"] == 1 and three["complete"] is True


def test_a_chain_with_a_node_twice_is_counted_not_shown(graph: GraphStore) -> None:
    graph.bulk_insert_or_update_edges(
        [
            _edge(LETTER, WATER),
            _edge(OTHER, MUNI),
            _edge(OTHER, WATER),
            _edge(BOTH, BOOK7),
        ]
    )
    build_source_steps(graph)
    found = get_chains(graph, (WATER, MUNI), max_steps=2, limit=1)

    one, two = found.blocks
    assert one.total == 1  # 36000, nr. 1 and 36496, nr. 3 name both
    # the letter names three sources, the other paper four: the letter
    assert (one.chains[0].steps[0].via, one.chains[0].steps[0].ways) == (LETTER, 2)
    # art. 1 Awb is the strongest, but only through the letter twice; then the Woningwet
    # and Boek 7 are as weak, and the Woningwet stronger together
    assert two.total == 3
    assert [c.sources for c in two.chains] == [(WATER, HOUSING, MUNI)]


def test_a_source_both_ends_share_starts_no_longer_chain(graph: GraphStore) -> None:
    found = get_chains(graph, (RULING, ART_1), max_steps=2, limit=12)

    one, two = found.blocks
    # the judgment cites art. 2 Awb, which art. 1 refers to: one step through it, and no
    # chain of two through it as a source between them
    assert [c.steps[0].via for c in one.chains] == [ART_2]
    assert two.total == 0


def test_the_weakest_step_ranks_a_chain_before_the_steps_together(
    store: GraphStore,
) -> None:
    a, b, strong, even, w, x, y, z = _articles(
        store, "a", "b", "c", "e", "w", "x", "y", "z"
    )
    _papers(
        store,
        {
            # a to c twice alone, c to b in a paper of four: strong, then weak
            "p1": [a, strong],
            "p2": [a, strong],
            "p3": [strong, b, w, x],
            # a to e and e to b each in a paper of three
            "p4": [a, even, y],
            "p5": [even, b, z],
        },
    )
    two = get_chains(store, (a, b), max_steps=2, limit=12).blocks[1]

    assert [c.sources[1] for c in two.chains] == [even, strong]
    assert two.chains[0].weight > two.chains[1].weight


def test_each_source_between_the_ends_is_in_one_chain_shown(store: GraphStore) -> None:
    a, b, c1, c2, d = _articles(store, "a", "b", "c1", "c2", "d")
    _papers(
        store,
        {"p1": [a, c1], "p2": [a, c2], "p3": [c1, d], "p4": [c2, d], "p5": [d, b]},
    )
    three = get_chains(store, (a, b), max_steps=3, limit=12).blocks[2]

    # two chains through d: counted both, shown the one through c1 (the lower id)
    assert three.total == 2
    assert [c.sources for c in three.chains] == [(a, c1, d, b)]


def test_a_step_names_the_shared_node_of_the_fewest_sources(store: GraphStore) -> None:
    a, b, z = _articles(store, "a", "b", "z")
    _papers(store, {"p3": [a, b], "p2": [a, b], "p1": [a, b, z]})
    (one,) = get_chains(store, (a, b), max_steps=1, limit=12).blocks

    (step,) = one.chains[0].steps
    # p1 names three sources; of p2 and p3 the lowest id; the edges from a
    assert (step.via, step.ways) == (f"{COLLECTION_DOCUMENTS}/p2", 3)
    edges = {
        row["key"]: (row["from_id"], row["to_id"])
        for row in store.query("SELECT key, from_id, to_id FROM edges")
    }
    assert [edges[e] for e in step.edges] == [
        (f"{COLLECTION_DOCUMENTS}/p2", a),
        (f"{COLLECTION_DOCUMENTS}/p2", b),
    ]


def test_the_table_names_the_way_the_edges_of_the_sources_give(
    graph: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A step takes the node the table names, as the edges of its sources would choose it,
    without reading those whole; a table without them reads the edges."""
    whole: list[tuple[str, str]] = []
    read_ways = chains_queries._read_ways

    def spy(store: GraphStore, ends: Any, pairs: list[tuple[str, str]]) -> Any:
        whole.extend(pairs)
        return read_ways(store, ends, pairs)

    monkeypatch.setattr(chains_queries, "_read_ways", spy)
    asked = [(WATER, BOOK7, 2), (MUNI, HOUSING, 3), (MUNI, AWB, 1), (AWB, HOUSING, 3)]
    quick = [get_chains(graph, (a, b), steps, 12) for a, b, steps in asked]
    assert whole == []
    vias = [s.via for c in quick[0].blocks[1].chains for s in c.steps]
    assert vias == [MVT, OTHER]

    graph.execute("UPDATE source_steps SET via = NULL")
    assert [get_chains(graph, (a, b), steps, 12) for a, b, steps in asked] == quick
    assert whole


def test_the_way_of_a_step_is_one_row_of_the_index(graph: GraphStore) -> None:
    """The table's row of a step is found by its first source and its weight, not by
    reading every step of a source that has thousands."""
    with graph.pool.connection() as conn:
        conn.execute("SET LOCAL enable_seqscan = off")
        plan = "\n".join(
            row[0]
            for row in conn.execute(
                "EXPLAIN " + chains_queries._VIAS_SQL,
                {"firsts": [WATER], "seconds": [HOUSING], "weights": [1.0]},
            )
        )
    assert re.search(r"Index Cond: .*\(weight = p\.weight\)", plan), plan


def test_four_to_six_steps_meet_between_the_ends(store: GraphStore) -> None:
    line = _articles(store, *(f"s{i}" for i in range(7)))
    _papers(store, {f"p{i}": [line[i], line[i + 1]] for i in range(6)})
    found = get_chains(store, (line[0], line[6]), max_steps=6, limit=12)

    assert [b.total for b in found.blocks] == [0, 0, 0, 0, 0, 1]
    (chain,) = found.blocks[5].chains
    assert chain.sources == tuple(line)
    assert [s.via for s in chain.steps] == [
        f"{COLLECTION_DOCUMENTS}/p{i}" for i in range(6)
    ]
    assert all(b.complete for b in found.blocks) and not found.capped
    # four steps and five, from the inner sources
    assert get_chains(store, (line[1], line[5]), 4, 12).blocks[3].total == 1
    assert get_chains(store, (line[0], line[5]), 5, 12).blocks[4].total == 1


def test_a_longer_search_that_leaves_a_way_out_is_a_lower_bound(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    a, b, c1, c2, d1, d2, m = _articles(store, "a", "b", "c1", "c2", "d1", "d2", "m")
    _papers(
        store,
        {
            "p1": [a, c1],
            "p2": [a, c2],
            "p3": [c1, m],
            "p4": [c2, m],
            "p5": [m, d1],
            "p6": [m, d2],
            "p7": [d1, b],
            "p8": [d2, b],
        },
    )
    monkeypatch.setattr(chains_queries, "FRONTIER_CAP", 1)
    found = get_chains(store, (a, b), max_steps=4, limit=12)

    four = found.blocks[3]
    assert (four.total, four.complete, found.capped) == (1, False, True)
    assert [b.complete for b in found.blocks[:3]] == [True, True, True]


def test_a_cut_level_makes_the_blocks_from_it_incomplete(
    graph: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(chains_queries, "LEVEL_CAP", 1)
    found = get_chains(graph, (MUNI, HOUSING), max_steps=3, limit=12)

    assert found.capped is True
    assert [b.complete for b in found.blocks] == [True, True, False]


def test_before_the_steps_are_built_the_chains_are_503(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        COLLECTION_INSTRUMENTS, [_node(NodeType.INSTRUMENT, k) for k in ("ws", "ww")]
    )
    app.dependency_overrides[get_store] = lambda: store
    try:
        response = TestClient(app).get(f"/api/chains?ids={WATER},{HOUSING}")
    finally:
        app.dependency_overrides.pop(get_store, None)
    assert_status(response, 503)


def test_a_request_without_two_nodes_is_refused(client: TestClient) -> None:
    assert_status(client.get(f"/api/chains?ids={WATER}"), 422)
    assert_status(client.get(f"/api/chains?ids={WATER},{WATER}"), 422)
    assert_status(client.get(f"/api/chains?ids={WATER},{BOOK7},{MUNI}"), 422)
    assert_status(client.get(f"/api/chains?ids={WATER},{BOOK7}&max_steps=7"), 422)
    assert_status(client.get(f"/api/chains?ids={WATER},instruments/nope"), 404)
