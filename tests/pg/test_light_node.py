"""The light node of an article (``limit=1``) does not wait for its lid counts: they read the
``meta`` of every edge citing it (thousands for 6:162 BW, 7.0 s cold after a deploy on 10
Oct). Not kept yet, it answers without them, says so (``lid_counts_pending``) and they are
counted on; a larger page waits for them, as the full Verbonden call needs."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.db import GraphStore, version_cache
from lawgraph.db.queries.dossiers import load_dossier_names


@contextmanager
def _pool_busy() -> Iterator[None]:
    """Every worker of the pool of the cache busy (a warm-up), until the block ends."""
    release = threading.Event()
    started = threading.Barrier(version_cache.WORKERS + 1)

    def hold() -> None:
        started.wait()
        release.wait(60)

    for _ in range(version_cache.WORKERS):
        version_cache._pool.submit(hold)
    started.wait(10)
    try:
        yield
    finally:
        release.set()


def _seed(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "articles",
        [{"_key": "bwbr0005289_162", "type": "article", "labels": [], "props": {
            "bwb_id": "BWBR0005289", "article_number": "162", "leden": ["1", "2", "3"]}}],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            {"_key": f"ecli_nl_hr_2020_{n}", "type": "judgment", "labels": [],
             "props": {"ecli": f"ECLI:NL:HR:2020:{n}", "source": "rechtspraak"}}
            for n in range(3)
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_edges(
        [
            {"_key": f"c{n}", "_from": f"judgments/ecli_nl_hr_2020_{n}",
             "_to": "articles/bwbr0005289_162", "relation": "REFERS_TO",
             "source": "rechtspraak-linker", "meta": {"lid": "2"}}
            for n in range(3)
        ]
    )  # fmt: skip


def _get(store: GraphStore, **params: Any) -> tuple[dict[str, Any], float]:
    app.dependency_overrides[get_store] = lambda: store
    try:
        began = time.monotonic()
        response = TestClient(app).get(
            "/api/nodes/articles/bwbr0005289_162", params=params
        )
        took = time.monotonic() - began
    finally:
        app.dependency_overrides.pop(get_store, None)
    assert response.status_code == 200, response.text
    return response.json(), took


def _lids(body: dict[str, Any]) -> list[Any]:
    return [b["lid_counts"] for b in body["neighbors"]["buckets"]]


def test_the_light_node_does_not_wait_for_lid_counts_not_kept(
    store: GraphStore,
) -> None:
    _seed(store)
    version_cache.clear()
    # kept by the warm-up early on (its second part): the names a neighbour is shown with
    load_dossier_names(store)
    with _pool_busy():
        light, took = _get(store, limit=1)
    assert took < 1.0
    assert light["lid_counts_pending"] is True
    assert _lids(light) == [None]
    # the full call waits for them (the pool is free again) and has them
    full, _ = _get(store, limit=200)
    assert full["lid_counts_pending"] is False
    assert _lids(full) == [{"2": 3}]
    # kept now: the light node has them too
    light, _ = _get(store, limit=1)
    assert light["lid_counts_pending"] is False
    assert _lids(light) == [{"2": 3}]
