"""``GET /api/chains`` on a real graph: chains of one, two and three steps between two laws."""

from __future__ import annotations

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


@pytest.fixture()
def graph(store: GraphStore) -> GraphStore:
    """The memorie 35133, nr. 3 names the Waterschapswet and the Woningwet; 36496, nr. 3
    the Woningwet and Boek 7: two steps from the Waterschapswet to Boek 7. The Gemeentewet
    refers to the Awb, two articles of the Awb refer to each other, a judgment cites the
    second and the Woningwet: three steps from the Gemeentewet to the Woningwet."""
    store.bulk_insert_or_update_nodes(
        COLLECTION_INSTRUMENTS,
        [
            _node(NodeType.INSTRUMENT, key, inbound_citation_count=n)
            for key, n in (("ws", 1), ("ww", 40), ("bw7", 2), ("gw", 3), ("awb", 90))
        ],
    )
    store.bulk_insert_or_update_nodes(
        COLLECTION_ARTICLES,
        [
            _node(NodeType.ARTICLE, "awb_1", inbound_citation_count=5),
            _node(NodeType.ARTICLE, "awb_2", inbound_citation_count=7),
        ],
    )
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
    # the edge between them before the paper that names both; the articles of the Awb
    # are its own here, an end
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


def test_the_heaviest_chain_first_and_the_rest_counted(graph: GraphStore) -> None:
    graph.bulk_insert_or_update_edges(
        [
            _edge(LETTER, WATER),
            _edge(OTHER, MUNI),
            _edge(OTHER, WATER),
            _edge(BOTH, BOOK7),
        ]
    )
    found = get_chains(graph, (WATER, MUNI), max_steps=2, limit=1)

    one, two = found.blocks
    assert one.total == 1  # 36000, nr. 1 and 36496, nr. 3 name both
    assert (one.chains[0].steps[0].via, one.chains[0].steps[0].ways) == (LETTER, 2)
    # the Woningwet (40) before Boek 7 (2), each a step from both; art. 1 Awb only
    # through the letter twice, which no chain passes twice
    assert two.total == 2
    assert [c.sources for c in two.chains] == [(WATER, HOUSING, MUNI)]


def test_a_source_both_ends_share_starts_no_longer_chain(graph: GraphStore) -> None:
    found = get_chains(graph, (RULING, ART_1), max_steps=2, limit=12)

    one, two = found.blocks
    # the judgment cites art. 2 Awb, which art. 1 refers to: one step through it, and no
    # chain of two through it as a source between them
    assert [c.steps[0].via for c in one.chains] == [ART_2]
    assert two.total == 0


def test_a_cut_level_makes_the_blocks_after_it_incomplete(
    graph: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(chains_queries, "LEVEL_CAP", 1)
    found = get_chains(graph, (WATER, BOOK7), max_steps=3, limit=12)

    assert found.capped is True
    assert [b.complete for b in found.blocks] == [False, False, False]


def test_a_request_without_two_nodes_is_refused(client: TestClient) -> None:
    assert_status(client.get(f"/api/chains?ids={WATER}"), 422)
    assert_status(client.get(f"/api/chains?ids={WATER},{WATER}"), 422)
    assert_status(client.get(f"/api/chains?ids={WATER},{BOOK7},{MUNI}"), 422)
    assert_status(client.get(f"/api/chains?ids={WATER},{BOOK7}&max_steps=4"), 422)
    assert_status(client.get(f"/api/chains?ids={WATER},instruments/nope"), 404)
