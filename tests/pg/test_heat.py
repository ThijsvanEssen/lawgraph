"""The heat of the whole graph on a real PostgreSQL: every window counted in one pass over
the edges, the same as counting each on its own; computed once for every variant asked at
the same moment; and off with ``LAWGRAPH_API_HEAT=false`` but for named nodes."""

from __future__ import annotations

import datetime as dt
import threading
import time
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


def test_every_window_of_one_pass_is_its_own_count(store: GraphStore) -> None:
    _graph(store)
    tops = overlay.get_heat_tops(store, 50)
    for months in overlay.HEAT_WINDOWS:
        for min_count in (1, 2):
            for limit in (1, 2, 3, 10):
                assert overlay.heat_top(tops, months, min_count, limit) == (
                    overlay.get_heat_counts(
                        store, months=months, min_count=min_count, limit=limit
                    )
                ), (months, min_count, limit)
    assert overlay.heat_top(tops, 3, 1, 10) == {
        "articles/a": 3,
        "articles/b": 1,
        "dossiers/1": 1,
    }


def test_variants_asked_at_once_are_counted_once(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _graph(store)
    passes: list[int] = []

    def counted(store_: GraphStore, top: int) -> dict[int, list[tuple[str, int]]]:
        passes.append(top)
        time.sleep(0.3)
        return overlay.get_heat_tops(store_, top)

    monkeypatch.setattr(nodes, "get_heat_tops", counted)
    answers: dict[str, dict[str, int]] = {}
    asks = {
        "3": lambda: nodes.heat_counts(store, months=3),
        "12/2": lambda: nodes.heat_counts(store, months=12, min_count=2),
        "5": lambda: nodes.heat_counts(store, months=5, limit=1),
    }
    threads = [
        threading.Thread(target=lambda n=n, ask=ask: answers.update({n: ask()}))
        for n, ask in asks.items()
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(passes) == 1
    assert answers["12/2"] == {"articles/a": 3, "dossiers/1": 2, "dossiers/2": 2}
    assert answers["5"] == {"articles/a": 3}  # 5 months counts as the window of 6


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
