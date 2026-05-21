"""Tests for the stats API route."""

from __future__ import annotations

from fastapi.testclient import TestClient

from lawgraph.api.app import app

client = TestClient(app)

_STATS_DATA = {
    "nodes": {"instruments": 100, "judgments": 50},
    "edges": {"total": 200, "by_relation": {"AMENDS_INSTRUMENT": 10}},
    "by_source": {"tk": {"publications": 30}},
    "instruments": {"by_kind": {}, "by_jurisdiction": {}},
}


def test_get_stats_returns_200(monkeypatch) -> None:
    monkeypatch.setattr(
        "lawgraph.api.routes.stats.get_db_stats",
        lambda store: _STATS_DATA,
    )
    response = client.get("/api/stats")
    assert response.status_code == 200
    body = response.json()
    assert "nodes" in body
    assert "edges" in body
