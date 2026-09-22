from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.queries.nodes import (
    NeighborBucket,
    NeighborEntry,
    NeighborFacet,
    NeighborFilter,
    NodeGraphData,
    NodeNotFoundError,
)
from lawgraph.api.schemas.nodes import NeighborDTO, node_type_of
from lawgraph.config.constants import RELATION_PART_OF, RELATION_REFERS_TO

client = TestClient(app)

_NODE_DOC = {
    "_id": "instruments/BWBR0000123",
    "_key": "BWBR0000123",
    "props": {"display_name": "Instrument A"},
    "labels": ["Instrument"],
}

_NEIGHBOR_DOC = {
    "_id": "articles/BWBR0000123-101",
    "_key": "BWBR0000123-101",
    "type": "article",
    "props": {"display_name": "Artikel 101", "text": "lang", "entries": [1]},
    "labels": ["Article"],
}

_EDGE = {
    "_key": "e1",
    "_from": "articles/BWBR0000123-101",
    "_to": "instruments/BWBR0000123",
    "relation": RELATION_PART_OF,
    "status": "voorgesteld",
    "confidence": 0.75,
    "meta": {"start": 3, "end": 9, "raw_match": "artikel 101", "qualifier": "lid 1"},
}


def _payload() -> NodeGraphData:
    return NodeGraphData(
        node=_NODE_DOC,
        buckets=[
            NeighborBucket(
                facet=NeighborFacet(RELATION_PART_OF, "inbound", "articles", 31),
                next_offset=30,
                entries=[
                    NeighborEntry(doc=_NEIGHBOR_DOC, edge=_EDGE, direction="inbound")
                ],
            ),
            NeighborBucket(
                facet=NeighborFacet(RELATION_REFERS_TO, "outbound", "judgments", 0),
                next_offset=None,
                entries=[],
            ),
        ],
    )


def test_get_node_neighbors_returns_404_for_unknown_collection(monkeypatch):
    """GET /api/nodes/{collection}/{key} returns 404 when the node is not found."""
    monkeypatch.setattr(
        "lawgraph.api.routes.nodes.get_node_with_neighbors",
        lambda store, collection, key, **kwargs: (_ for _ in ()).throw(
            NodeNotFoundError("node not found")
        ),
    )
    response = client.get("/api/nodes/instruments/nonexistent-key-xyz")
    assert response.status_code == 404


def test_get_node_graph_returns_buckets_of_neighbors(monkeypatch):
    """The node explorer endpoint, driven by a simulated graph."""
    seen: dict[str, Any] = {}

    def fake(store, collection, key, **kwargs):
        seen.update(kwargs)
        return _payload()

    monkeypatch.setattr("lawgraph.api.routes.nodes.get_node_with_neighbors", fake)

    response = client.get(
        "/api/nodes/instruments/BWBR0000123"
        "?relations=PART_OF,REFERS_TO&node_types=article&direction=inbound"
        "&status=voorgesteld&limit=10&offset=20"
    )
    assert response.status_code == 200
    payload = response.json()

    assert seen == {
        "filters": NeighborFilter(
            relations=("PART_OF", "REFERS_TO"),
            node_types=("article",),
            direction="inbound",
            status="voorgesteld",
        ),
        "limit": 10,
        "offset": 20,
    }
    node = payload["node"]
    assert node["id"].startswith("instruments")
    assert node["display_name"] == "Instrument A"

    neighbors = payload["neighbors"]
    assert neighbors["total"] == 31
    full, empty = neighbors["buckets"]
    assert (full["relation"], full["direction"], full["collection"]) == (
        "PART_OF",
        "inbound",
        "articles",
    )
    assert (full["type"], full["total"], full["next_offset"]) == ("article", 31, 30)
    assert empty["next_offset"] is None and empty["items"] == []

    (neighbor,) = full["items"]
    assert neighbor["id"] == "articles/BWBR0000123-101"  # the node, not the edge
    assert neighbor["edge_id"] == "e1"
    assert neighbor["status"] == "voorgesteld"
    assert neighbor["confidence"] == 0.75
    assert neighbor["meta"]["raw_match"] == "artikel 101"
    assert neighbor["props"] == {"display_name": "Artikel 101"}  # bulky props stay out


def test_get_node_graph_defaults_to_thirty_per_bucket_and_no_filter(monkeypatch):
    seen: dict[str, Any] = {}

    def fake(store, collection, key, **kwargs):
        seen.update(kwargs)
        return _payload()

    monkeypatch.setattr("lawgraph.api.routes.nodes.get_node_with_neighbors", fake)
    assert client.get("/api/nodes/instruments/x").status_code == 200
    assert seen == {"filters": NeighborFilter(), "limit": 30, "offset": 0}


def test_get_node_facets_returns_counts(monkeypatch):
    monkeypatch.setattr(
        "lawgraph.api.routes.nodes.get_node_facets",
        lambda store, collection, key, **kwargs: [
            NeighborFacet(RELATION_PART_OF, "inbound", "articles", 31),
            NeighborFacet(RELATION_REFERS_TO, "outbound", "judgments", 4),
        ],
    )
    body = client.get("/api/nodes/instruments/x/facets").json()
    assert body == {
        "items": [
            {
                "relation": "PART_OF",
                "direction": "inbound",
                "collection": "articles",
                "type": "article",
                "count": 31,
            },
            {
                "relation": "REFERS_TO",
                "direction": "outbound",
                "collection": "judgments",
                "type": "judgment",
                "count": 4,
            },
        ],
        "total": 35,
    }


@pytest.mark.parametrize("path", ["", "/facets", "/neighborhood"])
@pytest.mark.parametrize(
    "query",
    [
        "relations=NOPE",
        "relations=PART_OF,NOPE",
        "node_types=articles",
        "direction=sideways",
        "status=gone",
    ],
)
def test_the_filters_are_validated_before_the_database_is_asked(path, query):
    """The store of these tests is None: a 422 means no query was made."""
    assert client.get(f"/api/nodes/instruments/x{path}?{query}").status_code == 422


@pytest.mark.parametrize("query", ["limit=0", "limit=201", "offset=-1"])
def test_the_page_of_a_bucket_is_bounded(query):
    assert client.get(f"/api/nodes/instruments/x?{query}").status_code == 422


def test_unknown_collection_is_a_400_for_facets_and_neighborhood():
    for path in ("/facets", "/neighborhood"):
        response = client.get(f"/api/nodes/raw_sources/x{path}")
        assert response.status_code == 400


def test_neighbor_dto_takes_the_edge_as_it_is():
    dto = NeighborDTO.from_entry(_NEIGHBOR_DOC, _EDGE, "inbound", 0.75)
    assert dto.edge_id == "e1" and dto.id == "articles/BWBR0000123-101"
    assert dto.meta == _EDGE["meta"] and dto.status == "voorgesteld"

    bare = {"_key": "e2", "relation": RELATION_PART_OF}
    dto = NeighborDTO.from_entry(_NEIGHBOR_DOC, bare, "outbound", None)
    assert dto.status is None and dto.meta is None and dto.confidence is None


def test_the_type_of_a_neighbor_collection_is_read_from_the_collection():
    assert node_type_of("article_versions") == "article_version"
    assert node_type_of("annexes") == "annex"
    assert node_type_of("unknown") == ""
