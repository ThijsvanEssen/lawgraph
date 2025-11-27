from __future__ import annotations

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.queries import NeighborEntry, NodeGraphData

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


def _build_payload() -> NodeGraphData:
    strict = NeighborEntry(
        doc=_NEIGHBOR_DOC,
        relation="PART_OF_INSTRUMENT",
        direction="outbound",
        confidence=0.75,
    )
    semantic = NeighborEntry(
        doc=_NEIGHBOR_DOC,
        relation="MENTIONS_ARTICLE",
        direction="inbound",
        confidence=0.92,
    )
    return NodeGraphData(
        node=_NODE_DOC,
        strict_neighbors=[strict],
        semantic_neighbors=[semantic],
    )


def test_get_node_graph_returns_neighbors(monkeypatch):
    """Verifieer het node explorer endpoint via een gesimuleerde graph."""
    monkeypatch.setattr(
        "lawgraph.api.routes.nodes.get_node_with_neighbors",
        lambda store, collection, key: _build_payload(),
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
