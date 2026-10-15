"""A request whose client goes away stops reading the database: its running read is
cancelled at once and leaves no query behind (``CancelOnDisconnectMiddleware``)."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest
from fastapi import FastAPI

from lawgraph.api.middleware import CancelOnDisconnectMiddleware
from lawgraph.db import GraphStore, request_context
from lawgraph.db import store as store_module

SLEPT = 8  # seconds the query of a request reads
SLEEP = f"SELECT pg_sleep({SLEPT}) AS slept"


def _scope() -> dict[str, Any]:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/slow",
        "raw_path": b"/slow",
        "query_string": b"",
        "root_path": "",
        "headers": [],
        "client": ("127.0.0.1", 4711),
        "server": ("testserver", 80),
    }


def _sleeping(store: GraphStore) -> list[dict[str, Any]]:
    return [
        row
        for row in store_module.own_activity(0.0)
        if f"pg_sleep({SLEPT})" in row["query"]
    ]


def test_a_request_whose_client_goes_away_leaves_no_query_behind(
    store: GraphStore,
) -> None:
    app = FastAPI()

    @app.get("/slow")
    def slow() -> dict[str, Any]:
        return {"rows": list(store.query(SLEEP))}

    wrapped = CancelOnDisconnectMiddleware(app)

    async def request() -> float:
        messages = [{"type": "http.request", "body": b"", "more_body": False}]

        async def receive() -> dict[str, Any]:
            if messages:
                return messages.pop(0)
            await asyncio.sleep(0.5)  # the browser aborts, as at the next keystroke
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            return None

        began = time.monotonic()
        with pytest.raises(request_context.RequestCancelled):
            await wrapped(_scope(), receive, send)
        return time.monotonic() - began

    took = asyncio.run(request())
    assert took < SLEPT, (
        f"the request read on for {took:.1f} s after its client went away"
    )
    assert _sleeping(store) == []


def test_a_request_whose_client_stays_reads_to_the_end(store: GraphStore) -> None:
    """No disconnect: nothing is cancelled."""
    app = FastAPI()

    @app.get("/slow")
    def quick() -> dict[str, Any]:
        return {"rows": list(store.query("SELECT 1 AS one"))}

    wrapped = CancelOnDisconnectMiddleware(app)
    sent: list[dict[str, Any]] = []

    async def request() -> None:
        messages = [{"type": "http.request", "body": b"", "more_body": False}]

        async def receive() -> dict[str, Any]:
            if messages:
                return messages.pop(0)
            # as a server does: after the body, the next message is the client leaving
            await asyncio.Event().wait()
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            sent.append(message)

        await wrapped(_scope(), receive, send)

    asyncio.run(request())
    assert sent[0]["status"] == 200
