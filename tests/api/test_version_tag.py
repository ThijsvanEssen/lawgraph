"""The ``ETag`` of a response holds the data version, which ``CacheControlMiddleware``
keeps for ``VERSION_TTL`` and reads on a thread of its own: a request never waits for a
free worker of the pool the routes run on, nor longer than ``VERSION_WAIT`` for a read
once a version is known."""

from __future__ import annotations

import asyncio
import threading
from typing import Any, cast

import anyio.to_thread
import pytest
from starlette.types import Message

from lawgraph.api import middleware
from lawgraph.api.middleware import CacheControlMiddleware
from lawgraph.db import GraphStore, version_cache


async def _ok(scope, receive, send) -> None:
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"{}"})


class _Database:
    """A store whose data version is ``now``: each read counted, and held while ``slow``
    is not set."""

    name = "tagged"

    def __init__(self) -> None:
        self.now = "1"
        self.reads = 0
        self.slow = threading.Event()
        self.slow.set()

    def data_version(self) -> str:
        self.reads += 1
        assert self.slow.wait(10)
        return self.now


async def _etag(app: CacheControlMiddleware) -> str | None:
    sent: list[Message] = []

    async def receive() -> Message:
        return {"type": "http.request", "body": b""}

    async def send(message: Message) -> None:
        sent.append(message)

    scope: dict[str, Any] = {"type": "http", "method": "GET", "path": "/api/x"}
    await app(scope, receive, send)
    headers = dict(sent[0]["headers"])
    tag = headers.get(b"etag")
    return tag.decode() if tag else None


def _app(store: _Database) -> CacheControlMiddleware:
    return CacheControlMiddleware(
        _ok, store=lambda: cast(GraphStore, store), api_version="9.9.9"
    )


def test_a_request_does_not_wait_for_a_worker_of_the_routes() -> None:
    """Every worker of the pool the routes run on is taken (slow searches): the tag is
    read all the same (16 Oct: requests waited minutes for one before their log line)."""
    app = _app(_Database())

    async def run() -> str | None:
        limiter = anyio.to_thread.current_default_thread_limiter()
        limiter.total_tokens = 1
        route = object()  # a route that holds the last worker
        await limiter.acquire_on_behalf_of(route)
        try:
            return await asyncio.wait_for(_etag(app), 5)
        finally:
            limiter.release_on_behalf_of(route)

    assert asyncio.run(run()) == 'W/"9.9.9-1"'


def test_the_version_is_read_once_per_ttl_and_a_slow_read_is_not_waited_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Requests side by side share one read; within ``VERSION_TTL`` none reads; past it a
    request waits ``VERSION_WAIT`` at most for a read that hangs, and takes the version
    it knows."""
    monkeypatch.setattr(version_cache, "VERSION_TTL", 60.0)
    monkeypatch.setattr(middleware, "VERSION_WAIT", 0.05)
    monkeypatch.setattr(version_cache, "warm", lambda store: None)  # a new version
    versions = _Database()
    app = _app(versions)

    async def run() -> None:
        tags = await asyncio.gather(*(_etag(app) for _ in range(20)))
        assert set(tags) == {'W/"9.9.9-1"'} and versions.reads == 1
        await _etag(app)
        assert versions.reads == 1  # within the TTL

        monkeypatch.setattr(version_cache, "VERSION_TTL", 0.0)
        versions.now = "2"
        versions.slow.clear()  # the database does not answer
        tags = await asyncio.gather(*(_etag(app) for _ in range(20)))
        assert set(tags) == {'W/"9.9.9-1"'} and versions.reads == 2
        versions.slow.set()
        for _ in range(100):
            if await _etag(app) == 'W/"9.9.9-2"':
                return
            await asyncio.sleep(0.01)
        pytest.fail("the new version was never read")

    asyncio.run(run())
