"""The heat of the whole graph on a real PostgreSQL: every window counted in one pass over
the edges by ``semantic graph-heat``, the same as counting each on its own, kept in
``lg_heat`` and read there by the API, which never counts it; and off with
``LAWGRAPH_API_HEAT=false`` but for named nodes."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.api.routes import nodes
from lawgraph.db import GraphStore
from lawgraph.db.queries import overlay


def _ago(days: int) -> str:
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat()


def _edge(key: str, to: str, relation: str, **doc: Any) -> dict[str, Any]:
    return {
        "_key": key,
        "_from": "documents/d",
        "_to": to,
        "relation": relation,
        "source": "x",
        "status": "canoniek",
        "meta": {},
        **doc,
    }


def _graph(store: GraphStore) -> None:
    store.bulk_insert_or_update_edges(
        [
            _edge("1", "dossiers/1", "ABOUT", created_at=_ago(30)),
            _edge("2", "dossiers/1", "ABOUT", created_at=_ago(150)),
            _edge("3", "dossiers/2", "ABOUT", created_at=_ago(300)),
            _edge("4", "dossiers/2", "ABOUT", created_at=_ago(300)),
            _edge("5", "dossiers/3", "ABOUT", created_at=_ago(600)),
            _edge("6", "articles/a", "REFERS_TO", created_at="2000-01-01"),
            _edge("7", "articles/a", "REFERS_TO", created_at=_ago(60)),
            _edge("8", "articles/b", "AMENDS"),
            _edge("9", "dossiers/4", "ABOUT", created_at="2000-01-01"),
        ]
    )


def test_the_kept_heat_of_every_window_is_its_own_count(store: GraphStore) -> None:
    _graph(store)
    version = store.data_version()
    assert overlay.stored_heat(store, 3, 1, 10) is None  # never kept
    assert overlay.store_heat(store, 50) == 15  # one pass for every window
    for months in overlay.HEAT_WINDOWS:
        for min_count in (1, 2):
            for limit in (1, 2, 3, 10):
                assert overlay.stored_heat(store, months, min_count, limit) == (
                    overlay.get_heat_counts(
                        store, months=months, min_count=min_count, limit=limit
                    )
                ), (months, min_count, limit)
    assert overlay.stored_heat(store, 3, 1, 10) == {
        "articles/a": 3,
        "articles/b": 1,
        "dossiers/1": 1,
    }
    assert overlay.stored_heat(store, 5, 1, 1) == {"articles/a": 3}  # 5 counts as 6
    # keeping it is not a change of the graph: the caches of the API stay
    assert store.data_version() == version
    state = list(store.query("SELECT computed_at, data_version FROM lg_heat_state"))
    assert len(state) == 1 and state[0]["data_version"] == version


def test_keeping_the_heat_again_replaces_it(store: GraphStore) -> None:
    _graph(store)
    overlay.store_heat(store, 50)
    store.bulk_insert_or_update_edges(
        [_edge("10", "dossiers/9", "ABOUT", created_at=_ago(10))]
    )
    overlay.store_heat(store, 1)
    assert overlay.stored_heat(store, 3, 1, 10) == {"articles/a": 3}
    assert overlay.stored_heat(store, 24, 1, 10) == {"articles/a": 3}
    assert list(store.query("SELECT count(*)::int FROM lg_heat_state")) == [1]


def test_the_api_never_counts_the_heat_of_the_whole_graph(store: GraphStore) -> None:
    """Counting it reads every edge, which empties the page cache: the API reads what
    ``semantic graph-heat`` kept, and answers 503 until it has."""
    _graph(store)
    read: list[str] = []
    query = store.query

    def recording(statement: Any, params: Any = None, **options: Any) -> Any:
        read.append(str(statement))
        return query(statement, params, **options)

    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        store.query = recording  # type: ignore[method-assign]
        before = client.get("/api/nodes/heat")
        store.query = query  # type: ignore[method-assign]
        overlay.store_heat(store, 50)
        store.query = recording  # type: ignore[method-assign]
        after = client.get("/api/nodes/heat", params={"months": 12, "min_count": 2})
    finally:
        store.query = query  # type: ignore[method-assign]
        app.dependency_overrides.pop(get_store, None)
    assert before.status_code == 503
    assert after.status_code == 200
    assert after.json() == {"articles/a": 3, "dossiers/1": 2, "dossiers/2": 2}
    assert read and not [s for s in read if "edges" in s]


def test_the_heat_of_the_whole_graph_can_be_switched_off(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _graph(store)
    monkeypatch.setattr(nodes, "API_HEAT", False)
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        whole = client.get("/api/nodes/heat")
        named = client.get("/api/nodes/heat", params={"ids": "dossiers/1,articles/a"})
    finally:
        app.dependency_overrides.pop(get_store, None)
    assert whole.status_code == 503
    assert named.status_code == 200
    assert named.json() == {"articles/a": 3, "dossiers/1": 2}


def test_the_step_keeps_the_heat(store: GraphStore) -> None:
    from lawgraph.pipelines.semantic import graph_heat

    _graph(store)
    assert graph_heat.main([]).updated == 15
    assert overlay.stored_heat(store, 3, 1, 1) == {"articles/a": 3}
