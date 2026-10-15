"""The light node of an article (``limit=1``) does not wait for its lid counts: they read the
``meta`` of every edge citing it (thousands for 6:162 BW, 7.0 s cold after a deploy on 10
Oct). Not kept yet, it answers without them, says so (``lid_counts_pending``) and they are
counted on; a larger page waits for them, as the full Verbonden call needs."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.db import GraphStore, version_cache
from lawgraph.db.queries.dossiers import load_dossier_names
from tests.pg.plans import pool_busy


def _seed(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "articles",
        [{"key": "bwbr0005289_162", "type": "article", "labels": [], "props": {
            "bwb_id": "BWBR0005289", "article_number": "162"}}],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            {"key": f"ecli_nl_hr_2020_{n}", "type": "judgment", "labels": [],
             "props": {"ecli": f"ECLI:NL:HR:2020:{n}", "source": "rechtspraak"}}
            for n in range(3)
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_edges(
        [
            {"key": f"c{n}", "from_id": f"judgments/ecli_nl_hr_2020_{n}",
             "to_id": "articles/bwbr0005289_162", "relation": "REFERS_TO",
             "source": "rechtspraak-linker", "meta": {"lid": "2"}}
            for n in range(3)
        ]
    )  # fmt: skip


def _get(store: GraphStore, **params: Any) -> dict[str, Any]:
    app.dependency_overrides[get_store] = lambda: store
    try:
        response = TestClient(app).get(
            "/api/nodes/articles/bwbr0005289_162", params=params
        )
    finally:
        app.dependency_overrides.pop(get_store, None)
    assert response.status_code == 200, response.text
    return response.json()


def _lids(body: dict[str, Any]) -> list[Any]:
    return [b["lid_counts"] for b in body["neighbors"]["buckets"]]


def test_the_light_node_does_not_wait_for_lid_counts_not_kept(
    store: GraphStore,
) -> None:
    _seed(store)
    version_cache.clear()
    # kept by the warm-up early on (its second part): the names a neighbour is shown with
    load_dossier_names(store)
    with pool_busy():
        # answered while every worker is held: it did not wait for them
        light = _get(store, limit=1)
    assert light["lid_counts_pending"] is True
    assert _lids(light) == [None]
    # the full call waits for them (the pool is free again) and has them
    full = _get(store, limit=200)
    assert full["lid_counts_pending"] is False
    assert _lids(full) == [{"2": 3}]
    # kept now: the light node has them too
    light = _get(store, limit=1)
    assert light["lid_counts_pending"] is False
    assert _lids(light) == [{"2": 3}]
