"""A node with its neighbours, and its neighbourhood, on a real PostgreSQL."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.db import ArangoStore
from lawgraph.db.queries import nodes as node_queries


def _node(collection: str, key: str) -> tuple[str, dict[str, Any]]:
    node_type = {"dossiers": "dossier", "documents": "document", "members": "member"}[
        collection
    ]
    return collection, {
        "_key": key,
        "type": node_type,
        "labels": [],
        "props": {"k": key},
    }


def _edge(
    key: str, source: str, target: str, relation: str, status: str = "canoniek"
) -> dict:
    return {
        "_key": key,
        "_from": source,
        "_to": target,
        "relation": relation,
        "source": "tk",
        "status": status,
        "meta": {},
    }


@pytest.fixture()
def graph(store: ArangoStore) -> ArangoStore:
    for collection, doc in [
        _node("dossiers", "1"),
        _node("dossiers", "2"),
        _node("documents", "a"),
        _node("documents", "b"),
        _node("documents", "c"),
        _node("members", "m"),
    ]:
        store.bulk_insert_or_update_nodes(collection, [doc])
    store.bulk_insert_or_update_edges(
        [
            _edge("e1", "documents/a", "dossiers/1", "PART_OF"),
            _edge("e2", "documents/b", "dossiers/1", "PART_OF"),
            _edge("e3", "documents/c", "dossiers/1", "PART_OF", status="voorgesteld"),
            _edge("e4", "members/m", "documents/a", "AUTHORED"),
            _edge("e5", "documents/c", "dossiers/2", "PART_OF"),
            _edge(
                "e6", "dossiers/1", "dossiers/9", "RELATED_TO"
            ),  # to a node that is gone
        ]
    )
    return store


def test_a_node_with_its_neighbours_in_buckets(graph: ArangoStore) -> None:
    data = node_queries.get_node_with_neighbors(graph, "dossiers", "1", limit=2)
    assert data.node["_id"] == "dossiers/1"
    facets = [
        (b.facet.relation, b.facet.direction, b.facet.collection, b.facet.count)
        for b in data.buckets
    ]
    assert facets == [
        ("PART_OF", "inbound", "documents", 3),
        ("RELATED_TO", "outbound", "dossiers", 1),
    ]
    part_of = data.buckets[0]
    assert [e.doc["_id"] for e in part_of.entries] == ["documents/a", "documents/b"]
    assert part_of.next_offset == 2
    assert (
        part_of.entries[0].edge["_key"] == "e1"
        and part_of.entries[0].direction == "inbound"
    )
    assert data.buckets[1].entries == []  # its neighbour is gone
    second = node_queries.get_node_with_neighbors(
        graph, "dossiers", "1", limit=2, offset=2
    )
    assert [e.doc["_id"] for e in second.buckets[0].entries] == ["documents/c"]


def test_filters_on_relation_status_and_type(graph: ArangoStore) -> None:
    only = node_queries.NeighborFilter(status="voorgesteld")
    data = node_queries.get_node_with_neighbors(graph, "dossiers", "1", filters=only)
    assert [(b.facet.relation, b.facet.count) for b in data.buckets] == [("PART_OF", 1)]
    typed = node_queries.NeighborFilter(node_types=("dossier",))
    data = node_queries.get_node_with_neighbors(graph, "dossiers", "1", filters=typed)
    assert [b.facet.collection for b in data.buckets] == ["dossiers"]


def test_a_missing_node_and_an_unknown_collection(graph: ArangoStore) -> None:
    with pytest.raises(node_queries.NodeNotFoundError):
        node_queries.get_node_with_neighbors(graph, "dossiers", "x")
    with pytest.raises(node_queries.UnsupportedCollectionError):
        node_queries.get_node_with_neighbors(graph, "raw_sources", "x")


def test_the_neighbourhood_breadth_first(graph: ArangoStore) -> None:
    hood = node_queries.get_node_neighborhood(graph, "dossiers", "1", depth=2)
    assert hood["focal"]["_id"] == "dossiers/1"
    assert [n["_id"] for n in hood["nodes"]] == [
        "documents/a",
        "documents/b",
        "documents/c",
        "dossiers/2",
        "members/m",
    ]
    assert [e["_key"] for e in hood["edges"]] == ["e1", "e2", "e3", "e4", "e5"]


def test_a_capped_neighbourhood_keeps_the_first_level_first(graph: ArangoStore) -> None:
    hood = node_queries.get_node_neighborhood(graph, "dossiers", "1", depth=2, cap=4)
    assert [n["_id"] for n in hood["nodes"]] == [
        "documents/a",
        "documents/b",
        "documents/c",
        "dossiers/2",
    ]


def test_the_walk_goes_through_the_types_and_relations_asked_for(
    graph: ArangoStore,
) -> None:
    only_documents = node_queries.NeighborFilter(node_types=("document",))
    hood = node_queries.get_node_neighborhood(
        graph, "dossiers", "1", depth=3, filters=only_documents
    )
    assert [n["_id"] for n in hood["nodes"]] == [
        "documents/a",
        "documents/b",
        "documents/c",
    ]
    authored = node_queries.NeighborFilter(relations=("AUTHORED",), direction="inbound")
    hood = node_queries.get_node_neighborhood(graph, "documents", "a", filters=authored)
    assert [n["_id"] for n in hood["nodes"]] == ["members/m"]
    assert [e["_key"] for e in hood["edges"]] == ["e4"]


@pytest.mark.parametrize("cap", [2, 3, 4, 200])
def test_the_neighbours_looked_up_a_few_at_a_time(
    graph: ArangoStore, monkeypatch: pytest.MonkeyPatch, cap: int
) -> None:
    whole = node_queries.get_node_neighborhood(graph, "dossiers", "1", depth=2, cap=cap)
    # a chunk of two: dossiers/9 (gone) and the cap fall in different chunks
    monkeypatch.setattr(node_queries, "_NEIGHBOUR_CHUNK", 2)
    chunked = node_queries.get_node_neighborhood(
        graph, "dossiers", "1", depth=2, cap=cap
    )
    assert chunked == whole


def test_no_relation_asked_for_walks_nowhere(graph: ArangoStore) -> None:
    nothing = node_queries.NeighborFilter(relations=())
    hood = node_queries.get_node_neighborhood(graph, "dossiers", "1", filters=nothing)
    assert hood["nodes"] == [] and hood["edges"] == []
