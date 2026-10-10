"""``/api/stats`` on a real PostgreSQL: how long it waits once its kept counts expired."""

from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.db import GraphStore, version_cache


def test_the_stats_wait_once_for_counts_that_expired_together(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The counts of ``/api/stats`` (per table, the total of each list, kept while their
    tables stand still and ``MAX_AGE`` at most) are all computed by one warm-up, so they
    expire together and a request asks them one after another. It waits one
    ``STALE_WAIT`` in all and takes the kept counts, not one per count (11.8 s and a 503 on
    prod on 10 Oct, an hour after the warm-up)."""
    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            {"_key": f"j{n}", "type": "judgment", "labels": [],
             "props": {"ecli": f"ECLI:NL:HR:2020:{n}", "source": "rechtspraak",
                       "date_eff": "2020-01-01"}}
            for n in range(5)
        ],
    )  # fmt: skip
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        kept = client.get("/api/stats").json()
        # every kept count two hours old, and a new one slower than a request waits
        with version_cache._lock:
            for key, at in list(version_cache._computed_at.items()):
                version_cache._computed_at[key] = at - 7200
            for key, (value, at) in list(version_cache._lasting.items()):
                version_cache._lasting[key] = (value, at - 7200)
        computed = version_cache._compute

        def slow(entry_key: Any, compute: Any) -> Any:
            time.sleep(3)
            return computed(entry_key, compute)

        monkeypatch.setattr(version_cache, "_compute", slow)
        started = time.perf_counter()
        response = client.get("/api/stats")
        took = time.perf_counter() - started
    finally:
        app.dependency_overrides.pop(get_store, None)
    assert response.status_code == 200, response.text
    answer = response.json()
    assert answer["nodes"] == kept["nodes"]
    # the lists as kept (``decisions`` is null until its own count, never waited for, ran)
    assert {**answer["lists"], "decisions": None} == {
        **kept["lists"],
        "decisions": None,
    }
    assert kept["nodes"]["judgments"] == 5
    assert took < version_cache.STALE_WAIT + 1.5, took  # one wait, not one per count
