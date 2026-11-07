"""An answer that is ``partial`` (counts or a search cut off by their budget) is one to
ask again: ``Cache-Control: no-store`` and no ``ETag``, so a browser neither keeps it nor
gets a 304 for it until the data changes (B127: the Wetten kept empty filters)."""

from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from starlette.types import Message, Receive, Scope, Send

from lawgraph.api.app import app
from lawgraph.api.middleware import CacheControlMiddleware
from lawgraph.db import GraphStore
from tests.api.stubs import stub_route
from tests.asserts import assert_status

client = TestClient(app)

# the path of each list and the query its route asks
_LISTS = [
    ("/api/instruments", "instruments.get_instruments_list"),
    ("/api/judgments", "judgments.get_judgments_list"),
    ("/api/decisions", "decisions.get_decisions"),
    ("/api/documents", "documents.list_documents"),
]


@pytest.mark.parametrize(("path", "target"), _LISTS)
@pytest.mark.parametrize("partial", [True, False])
def test_a_partial_list_is_not_kept(
    monkeypatch: pytest.MonkeyPatch, path: str, target: str, partial: bool
) -> None:
    answer = {"total": None, "items": [], "facets": {}, "partial": partial}
    monkeypatch.setattr(f"lawgraph.api.routes.{target}", lambda *_, **__: answer)
    stub_route(monkeypatch, "documents", load_dossier_names={})
    stub_route(monkeypatch, "decisions", load_dossier_names={})
    response = client.get(path)
    assert_status(response, 200)
    assert response.json()["partial"] is partial
    if partial:
        assert response.headers["cache-control"] == "no-store"
        assert "etag" not in response.headers
    else:
        assert response.headers["cache-control"] == "private, max-age=60"


class _Database:
    name = "partial"

    def data_version(self) -> str:
        return "1"


async def _answer(app: CacheControlMiddleware) -> dict[bytes, bytes]:
    sent: list[Message] = []

    async def receive() -> Message:
        return {"type": "http.request", "body": b""}

    async def send(message: Message) -> None:
        sent.append(message)

    scope: dict[str, Any] = {"type": "http", "method": "GET", "path": "/api/x"}
    await app(scope, receive, send)
    return dict(sent[0]["headers"])


def _app(headers: list[tuple[bytes, bytes]]) -> CacheControlMiddleware:
    async def route(scope: Scope, receive: Receive, send: Send) -> None:
        start = {"type": "http.response.start", "status": 200, "headers": headers}
        await send(start)
        await send({"type": "http.response.body", "body": b"{}"})

    store = cast(GraphStore, _Database())
    return CacheControlMiddleware(route, store=lambda: store, api_version="9.9.9")


def test_the_middleware_keeps_the_no_store_of_a_route_and_tags_it_not() -> None:
    marked = asyncio.run(_answer(_app([(b"cache-control", b"no-store")])))
    plain = asyncio.run(_answer(_app([(b"cache-control", b"max-age=5")])))
    assert marked[b"cache-control"] == b"no-store"
    assert b"etag" not in marked
    assert plain[b"cache-control"] == b"private, max-age=60"
    assert plain[b"etag"] == b'W/"9.9.9-1"'
