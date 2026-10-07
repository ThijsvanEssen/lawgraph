"""What the API keeps of a visitor: the network of its address in the request log, never
the address or the query string; the full address only in the rate limiter's memory; the
terms of /api/search counted without who asked."""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from lawgraph.api import app as app_module
from lawgraph.api import search_terms
from lawgraph.api.app import _RateLimitMiddleware, app, truncated_ip
from lawgraph.api.dependencies import get_store


def test_an_address_is_cut_to_its_network() -> None:
    assert truncated_ip("203.0.113.77") == "203.0.113.0"
    assert truncated_ip("2001:db8:1234:5678::9") == "2001:db8:1234::"
    assert truncated_ip("-") == "-"
    assert truncated_ip("testclient") == "testclient"


def test_the_request_log_holds_no_address_and_no_query_string(caplog) -> None:
    client = TestClient(app, client=("203.0.113.77", 4711))
    with caplog.at_level(logging.INFO, logger=app_module.__name__):
        client.get("/api/health?q=rechtszaak+Jansen")
    lines = [r.getMessage() for r in caplog.records if r.name == app_module.__name__]
    logged = [line for line in lines if "/api/health" in line]
    assert logged, lines
    assert "203.0.113.0" in logged[0]
    assert "203.0.113.77" not in "\n".join(lines)
    assert "Jansen" not in "\n".join(lines) and "?" not in logged[0]


def test_the_rate_limit_still_counts_each_full_address(monkeypatch) -> None:
    """Two visitors of one /24 have a limit each: the limiter keys on the address."""
    import asyncio

    monkeypatch.setattr(app_module, "API_RATE_LIMIT_CALLS", 1)
    monkeypatch.setattr(app_module, "API_RATE_LIMIT_PERIOD", 60)

    async def ok(scope, receive, send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    limiter = _RateLimitMiddleware(ok)

    def status(address: str) -> int:
        sent: list[dict] = []

        async def send(message: dict) -> None:
            sent.append(message)

        async def receive() -> dict:
            return {"type": "http.request"}

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/health",
            "client": (address, 4711),
            "headers": [],
        }
        asyncio.run(limiter(scope, receive, send))
        return sent[0]["status"]

    assert status("203.0.113.7") == 200
    assert status("203.0.113.8") == 200  # the same /24, another visitor
    assert status("203.0.113.7") == 429


def test_a_search_counts_its_term_and_nothing_of_who_asked(monkeypatch) -> None:
    counted: list[str] = []

    class Counter:
        def add(self, q: str, today: object = None) -> None:
            counted.append(q)

    monkeypatch.setattr(search_terms, "COUNTER", Counter())
    app.dependency_overrides[get_store] = lambda: object()
    try:
        client = TestClient(app, raise_server_exceptions=False)
        client.get("/api/search", params={"q": "Rechtszaak  Jansen"})
        client.get(
            "/api/search", params={"q": "x", "types": "nope"}
        )  # 400: not counted
    finally:
        app.dependency_overrides.pop(get_store, None)
    assert counted == ["Rechtszaak  Jansen"]


@pytest.mark.parametrize("path", ["/api/health", "/api/stats"])
def test_other_routes_count_nothing(monkeypatch, path: str) -> None:
    counted: list[str] = []

    class Counter:
        def add(self, q: str, today: object = None) -> None:
            counted.append(q)

    monkeypatch.setattr(search_terms, "COUNTER", Counter())
    TestClient(app, raise_server_exceptions=False).get(path, params={"q": "Jansen"})
    assert counted == []
