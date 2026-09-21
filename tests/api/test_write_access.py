"""Nothing is written through the API without a key, and no route can forget to ask."""

from __future__ import annotations

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import refuse_open_writes, require_write_key

client = TestClient(app)

WRITES = [
    ("post", "/api/watches", {"node_id": "articles/x"}),
    ("delete", "/api/watches/w1", None),
    ("post", "/api/relationships/abc/vote", {"vote": "upvote"}),
]


@pytest.mark.parametrize(("method", "path", "body"), WRITES)
def test_a_write_is_closed_until_a_key_is_configured(
    monkeypatch, method: str, path: str, body: dict | None
) -> None:
    """Watches and votes were open to anyone who could reach the API."""
    monkeypatch.delenv("LAWGRAPH_WRITE_API_KEY", raising=False)
    response = client.request(method, path, json=body)
    assert response.status_code == 503
    assert "LAWGRAPH_WRITE_API_KEY" in response.json()["detail"]


@pytest.mark.parametrize(("method", "path", "body"), WRITES)
def test_a_write_without_the_key_or_with_a_wrong_one_is_refused(
    monkeypatch, method: str, path: str, body: dict | None
) -> None:
    monkeypatch.setenv("LAWGRAPH_WRITE_API_KEY", "secret")
    assert client.request(method, path, json=body).status_code == 401
    wrong = client.request(method, path, json=body, headers={"X-Write-Key": "nope"})
    assert wrong.status_code == 401


def test_reading_needs_no_key(monkeypatch) -> None:
    monkeypatch.delenv("LAWGRAPH_WRITE_API_KEY", raising=False)
    assert client.get("/api/relationships/types").status_code == 200


def test_the_app_does_not_start_with_a_write_route_that_asks_for_no_key() -> None:
    """At start-up, not in a test someone has to remember: a new POST without a key
    dependency is refused where it is added."""
    router = APIRouter()

    @router.post("/things")
    def create_thing() -> dict:
        return {}

    open_app = FastAPI()
    open_app.include_router(router)
    with pytest.raises(RuntimeError, match=r"POST /things.*asks for no key"):
        refuse_open_writes(open_app)

    closed = APIRouter()

    @closed.post("/things", dependencies=[])
    def create_with_key(
        _: None = pytest.importorskip("fastapi").Depends(require_write_key),
    ) -> dict:
        return {}

    closed_app = FastAPI()
    closed_app.include_router(closed)
    refuse_open_writes(closed_app)  # does not raise


def test_every_write_route_of_the_real_app_asks_for_a_key() -> None:
    refuse_open_writes(app)
