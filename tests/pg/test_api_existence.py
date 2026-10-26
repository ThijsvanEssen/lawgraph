"""What the API asks the store about a node's existence, run for real on the test server.

`/cited-by` of an article that is not there is a 404, and `/api/health` says whether the
database answers.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.api.middleware import VERSION_WAIT
from lawgraph.config.constants import COLLECTION_ARTICLES
from lawgraph.core.models import make_node_key
from lawgraph.db import GraphStore
from lawgraph.db.store import PING_WAIT
from tests.asserts import assert_status

BW7 = "BWBR0005290"
HELD = 2.0  # seconds every connection of the pool is taken
# a book of the BW numbers its articles without the book, as the graph stores them
KEY = make_node_key(BW7, "231")


@pytest.fixture()
def client(store: GraphStore) -> Iterator[TestClient]:
    doc = {
        "key": KEY,
        "type": "article",
        "labels": [],
        "props": {"bwb_id": BW7, "article_number": "231", "text": "Tekst."},
    }
    store.bulk_insert_or_update_nodes(COLLECTION_ARTICLES, [doc])
    app.dependency_overrides[get_store] = lambda: store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_store, None)


def test_cited_by_of_an_article_that_is_not_there_is_a_404(client: TestClient) -> None:
    assert_status(client.get(f"/api/articles/{BW7}/231/cited-by"), 200)
    assert_status(client.get(f"/api/articles/{BW7}/7:231/cited-by"), 200)
    assert_status(client.get(f"/api/articles/{BW7}/9:999/cited-by"), 404)


def test_the_health_check_asks_the_database(client: TestClient) -> None:
    # ``warm`` null: the suite runs the API without its warm-up
    health = client.get("/api/health").json()
    assert {k: health[k] for k in ("status", "database", "warm")} == {
        "status": "ok",
        "database": "connected",
        "warm": None,
    }
    assert health["version"] == app.version
    # the pools: the background one opens when it is first needed
    assert health["pools"]["requests"]["size"] > 0
    assert set(health["pools"]["requests"]) == {"size", "free", "waiting"}


def test_a_health_check_waiting_for_the_pool_holds_up_no_other_request(
    client: TestClient, store: GraphStore
) -> None:
    """The health check waits for a connection on a thread, not on the event loop: while
    every connection is taken, another request is answered at once, past the data version
    of its cache headers that it waits ``VERSION_WAIT`` for (23 Oct: a health check that
    waited on the loop held up every request, and none was logged)."""
    # the data version of the cache headers known, as it is after the first request
    assert_status(client.get("/"), 200)
    held = [store.pool.getconn() for _ in range(store.pool.get_stats()["pool_size"])]

    def give_back() -> None:
        time.sleep(HELD)
        for conn in held:
            store.pool.putconn(conn)

    threading.Thread(target=give_back, daemon=True).start()

    async def both() -> tuple[httpx.Response, httpx.Response, float]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            health = asyncio.create_task(c.get("/api/health"))
            await asyncio.sleep(0.1)
            began = time.monotonic()
            root = await c.get("/")
            took = time.monotonic() - began
            return await health, root, took

    health, root, took = asyncio.run(both())
    assert_status(root, 200)
    assert took < VERSION_WAIT + 0.5 < HELD, (
        f"the root waited {took:.1f} s for the health check"
    )
    assert_status(health, 200)


def test_a_health_check_answers_within_its_wait_when_the_pool_stays_held(
    client: TestClient, store: GraphStore
) -> None:
    """While every connection stays held, the health check says so within ``PING_WAIT``,
    not after the deadline of the request (23 Oct 19:50 UTC: 30 s per check, so a watch
    of it saw a timeout, not the 503)."""
    # the data version of the cache headers known, as it is after the first request
    assert_status(client.get("/"), 200)
    held = [store.pool.getconn() for _ in range(store.pool.get_stats()["pool_size"])]
    try:
        began = time.monotonic()
        health = client.get("/api/health")
        took = time.monotonic() - began
    finally:
        for conn in held:
            store.pool.putconn(conn)
    assert_status(health, 503)
    assert took < PING_WAIT + 1, f"the health check took {took:.1f} s"
