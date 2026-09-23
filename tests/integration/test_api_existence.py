"""What the API asks the store about a node's existence, run for real on the test server.

A watch is only made for a node that is there, `/cited-by` of an article that is not there is
a 404, and `/api/health` says whether the database answers.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import COLLECTION_ARTICLES
from lawgraph.core.models import make_node_key
from lawgraph.db import ArangoStore

BW7 = "BWBR0005290"
KEY = make_node_key(BW7, "7:231")


@pytest.fixture()
def client(database: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("LAWGRAPH_WRITE_API_KEY", "secret")
    store = ArangoStore()
    doc = {
        "_key": KEY,
        "type": "article",
        "labels": [],
        "props": {"bwb_id": BW7, "article_number": "7:231", "text": "Tekst."},
    }
    store.bulk_insert_or_update_nodes(COLLECTION_ARTICLES, [doc])
    app.dependency_overrides[get_store] = lambda: store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_store, None)


def _watch(client: TestClient, node_id: str) -> int:
    answer = client.post(
        "/api/watches", json={"node_id": node_id}, headers={"X-Write-Key": "secret"}
    )
    return answer.status_code


def test_a_watch_is_made_for_a_node_that_is_there(client: TestClient) -> None:
    assert _watch(client, f"{COLLECTION_ARTICLES}/{KEY}") == 201


@pytest.mark.parametrize(
    "node_id",
    [
        f"{COLLECTION_ARTICLES}/nothing",  # a collection of ours, no such key
        f"_users/{KEY}",  # not a collection of ours
        "no_such_collection/x",
    ],
)
def test_a_watch_for_a_node_that_is_not_there_is_refused(
    client: TestClient, node_id: str
) -> None:
    assert _watch(client, node_id) == 400


def test_cited_by_of_an_article_that_is_not_there_is_a_404(client: TestClient) -> None:
    assert client.get(f"/api/articles/{BW7}/7:231/cited-by").status_code == 200
    assert client.get(f"/api/articles/{BW7}/9:999/cited-by").status_code == 404


def test_the_health_check_asks_the_database(client: TestClient) -> None:
    assert client.get("/api/health").json() == {
        "status": "ok",
        "database": "connected",
    }
