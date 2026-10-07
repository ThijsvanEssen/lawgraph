"""A node with its neighbours, and its neighbourhood, on a real PostgreSQL."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.db import GraphStore
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
def graph(store: GraphStore) -> GraphStore:
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


def test_a_node_with_its_neighbours_in_buckets(graph: GraphStore) -> None:
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


def test_filters_on_relation_status_and_type(graph: GraphStore) -> None:
    only = node_queries.NeighborFilter(status="voorgesteld")
    data = node_queries.get_node_with_neighbors(graph, "dossiers", "1", filters=only)
    assert [(b.facet.relation, b.facet.count) for b in data.buckets] == [("PART_OF", 1)]
    typed = node_queries.NeighborFilter(node_types=("dossier",))
    data = node_queries.get_node_with_neighbors(graph, "dossiers", "1", filters=typed)
    assert [b.facet.collection for b in data.buckets] == ["dossiers"]


def test_a_missing_node_and_an_unknown_collection(graph: GraphStore) -> None:
    with pytest.raises(node_queries.NodeNotFoundError):
        node_queries.get_node_with_neighbors(graph, "dossiers", "x")
    with pytest.raises(node_queries.UnsupportedCollectionError):
        node_queries.get_node_with_neighbors(graph, "raw_sources", "x")


def test_the_neighbourhood_breadth_first(graph: GraphStore) -> None:
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


def test_a_capped_neighbourhood_keeps_the_first_level_first(graph: GraphStore) -> None:
    hood = node_queries.get_node_neighborhood(graph, "dossiers", "1", depth=2, cap=4)
    assert [n["_id"] for n in hood["nodes"]] == [
        "documents/a",
        "documents/b",
        "documents/c",
        "dossiers/2",
    ]


def test_the_walk_goes_through_the_types_and_relations_asked_for(
    graph: GraphStore,
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
    graph: GraphStore, monkeypatch: pytest.MonkeyPatch, cap: int
) -> None:
    whole = node_queries.get_node_neighborhood(graph, "dossiers", "1", depth=2, cap=cap)
    # a chunk of two: dossiers/9 (gone) and the cap fall in different chunks
    monkeypatch.setattr(node_queries, "_NEIGHBOUR_CHUNK", 2)
    chunked = node_queries.get_node_neighborhood(
        graph, "dossiers", "1", depth=2, cap=cap
    )
    assert chunked == whole


def test_no_relation_asked_for_walks_nowhere(graph: GraphStore) -> None:
    nothing = node_queries.NeighborFilter(relations=())
    hood = node_queries.get_node_neighborhood(graph, "dossiers", "1", filters=nothing)
    assert hood["nodes"] == [] and hood["edges"] == []


def test_a_neighbour_carries_no_text_and_the_node_itself_does(
    store: GraphStore,
) -> None:
    """The sections and footnotes of a paper are its text: a neighbour, a node of a
    neighbourhood or of a path is light; the node itself keeps them."""
    from lawgraph.db.queries.paths import get_paths

    paper = {
        "_key": "a",
        "type": "document",
        "labels": [],
        "props": {
            "title": "Memorie",
            "sections": [{"heading": "1", "text": "lang"}],
            "summary": "kort",
            "footnotes": [{"n": 1, "text": "voetnoot"}],
        },
    }
    store.bulk_insert_or_update_nodes("documents", [paper])
    store.bulk_insert_or_update_nodes("dossiers", [_node("dossiers", "1")[1]])
    store.bulk_insert_or_update_edges(
        [_edge("e1", "documents/a", "dossiers/1", "PART_OF")]
    )
    light = {"title": "Memorie", "summary": "kort"}

    data = node_queries.get_node_with_neighbors(store, "dossiers", "1")
    (entry,) = [e for bucket in data.buckets for e in bucket.entries]
    assert entry.doc["props"] == light  # in their order, without the text
    assert list(entry.doc["props"]) == ["title", "summary"]

    around = node_queries.get_node_neighborhood(store, "dossiers", "1", depth=1)
    assert [n["props"] for n in around["nodes"]] == [light]

    paths = get_paths(store, ["dossiers/1", "documents/a"], max_depth=2)
    assert "documents/a" in [n["_id"] for n in paths["nodes"]]
    assert all(
        "sections" not in n["props"] and "footnotes" not in n["props"]
        for n in paths["nodes"]
    )

    own = node_queries.get_node_with_neighbors(store, "documents", "a")
    assert own.node["props"] == paper["props"]


def test_an_article_as_a_neighbour_carries_no_structure(store: GraphStore) -> None:
    """Its parts, references and breadcrumb (and its text) are for the reader of the article:
    three quarters of what the articles of a law weigh as neighbours of the law."""
    article = {
        "_key": "w_1",
        "type": "article",
        "labels": [],
        "props": {
            "article_number": "1",
            "text": "Lid 1.",
            "parts": [{"kind": "lid", "number": "1"}],
            "heading": "Begrippen",
            "references": [{"target": "w_2"}],
            "breadcrumb": [{"label": "Hoofdstuk 1"}],
        },
    }
    law = {"_key": "w", "type": "instrument", "labels": [], "props": {"title": "Wet"}}
    store.bulk_insert_or_update_nodes("articles", [article])
    store.bulk_insert_or_update_nodes("instruments", [law])
    store.bulk_insert_or_update_edges(
        [_edge("p1", "articles/w_1", "instruments/w", "PART_OF")]
    )

    data = node_queries.get_node_with_neighbors(store, "instruments", "w")
    (entry,) = [e for bucket in data.buckets for e in bucket.entries]
    assert entry.doc["props"] == {"article_number": "1", "heading": "Begrippen"}
