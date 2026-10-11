"""The requests of one process share a bounded set of worker threads: a request leaves
none behind, also not when its client goes away (``_CancelOnDisconnectMiddleware``).

A server sends ``http.disconnect`` after every response, so the middleware sees one at the
end of each request, just as the request itself ends."""

from __future__ import annotations

import asyncio
import threading
from typing import Any

import anyio.to_thread

from lawgraph.api.app import _CancelOnDisconnectMiddleware

REQUESTS = 300
# a sequential stream of requests needs a worker or two; a leak is one per few requests
BOUND = 8


def _scope() -> dict[str, Any]:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "root_path": "",
        "headers": [],
        "client": ("127.0.0.1", 4711),
        "server": ("testserver", 80),
    }


async def _app(scope, receive, send) -> None:
    """A route with a sync step, as FastAPI runs a sync dependency or route; after its
    answer it winds down over a few steps of the event loop, as Starlette's middleware do."""
    await anyio.to_thread.run_sync(lambda: None)
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"{}", "more_body": False})
    for _ in range(scope["steps"]):
        await asyncio.sleep(0)


async def _request(app, steps: int, client_leaves_early: bool) -> None:
    messages = [{"type": "http.request", "body": b"", "more_body": False}]
    answered = asyncio.Event()

    async def receive() -> dict[str, Any]:
        if messages:
            return messages.pop(0)
        if not client_leaves_early:
            await answered.wait()  # as uvicorn: the disconnect follows the response
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.body" and not message.get("more_body"):
            answered.set()

    await app(_scope() | {"steps": steps}, receive, send)


def test_requests_leave_no_worker_threads_behind() -> None:
    app = _CancelOnDisconnectMiddleware(_app)

    async def serve() -> int:
        before = threading.active_count()
        for number in range(REQUESTS):
            await _request(app, number % 6, client_leaves_early=number % 7 == 0)
        await asyncio.sleep(0.1)
        return threading.active_count() - before

    added = asyncio.run(serve())
    assert added <= BOUND, f"{added} more threads after {REQUESTS} requests"
