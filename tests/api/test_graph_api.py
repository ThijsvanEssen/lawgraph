"""The relation and node type filters of the graph layers, up to the query."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.queries.graph import GlobalGraphData, InstrumentLayerData
from lawgraph.api.routes import graph as graph_routes

client = TestClient(app)


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph_routes, "_layer_cache", graph_routes.TTLCache(maxsize=16))


def _empty_global() -> GlobalGraphData:
    return GlobalGraphData(instruments=[], articles=[], judgments=[], edges=[])


def test_the_global_graph_takes_node_types_and_relations(monkeypatch) -> None:
    seen: dict[str, Any] = {}

    def fake(store, **kwargs):
        seen.update(kwargs)
        return _empty_global()

    monkeypatch.setattr(graph_routes, "get_global_graph", fake)
    response = client.get(
        "/api/graph/global?node_types=instrument,article&relations=PART_OF"
    )
    assert response.status_code == 200
    assert seen == {
        "node_types": ("instrument", "article"),
        "relations": ("PART_OF",),
        "max_judgments": 500,
    }

    client.get("/api/graph/global")
    assert seen["node_types"] == ("instrument", "article", "judgment")
    assert len(seen["relations"]) == 5


def test_each_filter_has_its_own_cache_entry(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake(store, **kwargs):
        calls.append(kwargs)
        return _empty_global()

    monkeypatch.setattr(graph_routes, "get_global_graph", fake)
    for query in (
        "",
        "?relations=PART_OF",
        "?relations=PART_OF",
        "?node_types=judgment",
    ):
        client.get(f"/api/graph/global{query}")
    assert len(calls) == 3


def test_the_instrument_layer_takes_relations(monkeypatch) -> None:
    seen: dict[str, Any] = {}

    def fake(store, **kwargs):
        seen.update(kwargs)
        return InstrumentLayerData(instruments=[], edges=[], stats={})

    monkeypatch.setattr(graph_routes, "get_instrument_layer_graph", fake)
    assert client.get("/api/graph/instruments?relations=AMENDS").status_code == 200
    assert seen == {"relations": ("AMENDS",)}


@pytest.mark.parametrize(
    "url",
    [
        "/api/graph/global?relations=VOTED",
        "/api/graph/global?node_types=member",
        "/api/graph/instruments?relations=PART_OF",
    ],
)
def test_a_value_the_layer_never_has_is_refused(url: str) -> None:
    assert client.get(url).status_code == 422
