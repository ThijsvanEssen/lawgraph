"""``/api/stats`` ``lists``: per list the ``total`` its endpoint gives without a filter, and
``decisions`` from the count that list keeps, null until it is counted."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.db import GraphStore
from tests.integration.seed import seed

LISTS = {
    "instruments": ("/api/instruments", {}),
    "judgments": ("/api/judgments", {}),
    "dossiers": ("/api/dossiers", {}),
    "documents": ("/api/documents", {}),
    "members": ("/api/members", {}),
    "bewindspersonen": ("/api/members", {"government": "true"}),
    "factions": ("/api/factions", {}),
    "committees": ("/api/committees", {}),
    "cabinets": ("/api/cabinets", {}),
    "commitments": ("/api/commitments", {}),
}


def _total(body: Any) -> int:
    return len(body) if isinstance(body, list) else int(body["total"])


def test_every_list_count_of_the_stats_equals_its_list(database: str, cli: Any) -> None:
    store = GraphStore()
    seed(store, documents=96, judgments=5, regulations=3)
    cli("normalize", "all")
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)

        def get(path: str, **params: Any) -> Any:
            response = client.get(path, params=params)
            assert response.status_code == 200, response.text
            return response.json()

        before = get("/api/stats")["lists"]
        decisions = get("/api/decisions", chamber="TK")
        after = get("/api/stats")["lists"]
        totals = {
            name: _total(get(path, **params)) for name, (path, params) in LISTS.items()
        }
    finally:
        app.dependency_overrides.pop(get_store, None)

    assert {name: after[name] for name in LISTS} == totals
    assert totals["judgments"] > 0 and totals["dossiers"] > 0
    assert before["decisions"] in (None, decisions["total"])
    assert decisions["total"] > 0
    assert after["decisions"] == decisions["total"]
