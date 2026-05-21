from __future__ import annotations

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.queries import NeighborEntry, NodeGraphData
from lawgraph.api.queries.nodes import NodeNotFoundError

client = TestClient(app)

_NODE_DOC = {
    "_id": "instruments/BWBR0000123",
    "_key": "BWBR0000123",
    "props": {"display_name": "Instrument A"},
    "labels": ["Instrument"],
}

_NEIGHBOR_DOC = {
    "_id": "instrument_articles/BWBR0000123-101",
    "_key": "BWBR0000123-101",
    "props": {"display_name": "Artikel 101"},
    "labels": ["Article"],
}


_PAYLOAD = NodeGraphData(
    node=_NODE_DOC,
    neighbors=[
        NeighborEntry(
            doc=_NEIGHBOR_DOC,
            relation="PART_OF_INSTRUMENT",
            direction="outbound",
            confidence=0.75,
        ),
        NeighborEntry(
            doc=_NEIGHBOR_DOC,
            relation="MENTIONS_ARTICLE",
            direction="inbound",
            confidence=0.92,
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


def test_get_node_graph_returns_neighbors(monkeypatch):
    """Verifieer het node explorer endpoint via een gesimuleerde graph."""
    monkeypatch.setattr(
        "lawgraph.api.routes.nodes.get_node_with_neighbors",
        lambda store, collection, key, **kwargs: _PAYLOAD,
    )

    response = client.get("/api/nodes/instruments/BWBR0000123")
    assert response.status_code == 200
    payload = response.json()

    node = payload["node"]
    assert node["id"].startswith("instruments")
    assert node["type"] is not None
    assert node["display_name"] == "Instrument A"

    neighbors = payload["neighbors"]
    assert isinstance(neighbors["strict"], list)
    assert isinstance(neighbors["semantic"], list)

    strict_neighbor = neighbors["strict"][0]
    assert "relation" in strict_neighbor
    assert "direction" in strict_neighbor
    assert "confidence" in strict_neighbor
