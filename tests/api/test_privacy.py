"""What the API keeps of a visitor: the network of its address in the request log, never
the address or the query string; the address (of IPv6 its /64) only in the rate limiter's
memory; the terms of /api/search counted without who asked."""

from __future__ import annotations

import logging
from collections import Counter

import pytest
from fastapi.testclient import TestClient
from starlette.types import Message

from lawgraph.api import middleware, search_terms
from lawgraph.api.app import app
from lawgraph.api.middleware import RateLimitMiddleware, truncated_ip
from lawgraph.core.search_stats import MIN_COUNT, SearchTermCounter


def test_an_address_is_cut_to_its_network() -> None:
    assert truncated_ip("203.0.113.77") == "203.0.113.0"
    assert truncated_ip("2001:db8:1234:5678::9") == "2001:db8:1234::"
    assert truncated_ip("-") == "-"
    assert truncated_ip("testclient") == "testclient"


def test_the_request_log_holds_no_address_and_no_query_string(caplog) -> None:
    # the stub store makes it a 500: its line holds no more than any other
    client = TestClient(
        app, client=("203.0.113.77", 4711), raise_server_exceptions=False
    )
    with caplog.at_level(logging.INFO, logger=middleware.__name__):
        client.get("/api/health?q=rechtszaak+Jansen")
    lines = [r.getMessage() for r in caplog.records if r.name == middleware.__name__]
    logged = [line for line in lines if "/api/health" in line]
    assert logged, lines
    assert "203.0.113.0" in logged[0]
    assert "203.0.113.77" not in "\n".join(lines)
    assert "Jansen" not in "\n".join(lines) and "?" not in logged[0]


def test_the_rate_limit_still_counts_each_full_address(monkeypatch) -> None:
    """Two visitors of one /24 have a limit each: the limiter keys on the address."""
    import asyncio

    monkeypatch.setattr(middleware, "RATE_LIMIT_CALLS", 1)
    monkeypatch.setattr(middleware, "RATE_LIMIT_PERIOD", 60)

    async def ok(scope, receive, send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    limiter = RateLimitMiddleware(ok)

    def status(address: str) -> int:
        sent: list[Message] = []

        async def send(message: Message) -> None:
            sent.append(message)

        async def receive() -> Message:
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

    class Counting:
        def add(self, q: str, today: object = None) -> None:
            counted.append(q)

    monkeypatch.setattr(search_terms, "COUNTER", Counting())
    client = TestClient(app, raise_server_exceptions=False)
    live = {"mode": "live", "resolve": "true"}
    client.get("/api/search", params={"q": "Rechtszaak  Jansen", **live})
    client.get("/api/search", params={"q": "x", "types": "nope", **live})  # 400
    assert counted == ["Rechtszaak  Jansen"]


def _lanes(client: TestClient, q: str, mode: str = "live") -> None:
    """The requests of one query of the explorer: one per lane, the first resolves."""
    for lane, types in enumerate(("members", "articles", "judgments")):
        params = {"q": q, "types": types, "mode": mode}
        client.get(
            "/api/search", params=params | ({"resolve": "true"} if lane == 0 else {})
        )


def test_a_query_counts_once_whatever_its_lanes(monkeypatch) -> None:
    """The lanes of one query count it once; a term asked twice stays under the count
    a month file keeps, and "Meer …" (``mode=full``) asks the same query again."""
    counter = SearchTermCounter()
    monkeypatch.setattr(search_terms, "COUNTER", counter)
    client = TestClient(app, raise_server_exceptions=False)
    _lanes(client, "huurrecht")
    assert sum(counter.take().values(), Counter()) == Counter({"huurrecht": 1})
    _lanes(client, "jansen")
    _lanes(client, "jansen")
    _lanes(client, "jansen", mode="full")
    counted = sum(counter.take().values(), Counter())
    assert counted == Counter({"jansen": 2})
    assert counted["jansen"] < MIN_COUNT


@pytest.mark.parametrize("path", ["/api/health", "/api/stats"])
def test_other_routes_count_nothing(monkeypatch, path: str) -> None:
    counted: list[str] = []

    class Counting:
        def add(self, q: str, today: object = None) -> None:
            counted.append(q)

    monkeypatch.setattr(search_terms, "COUNTER", Counting())
    TestClient(app, raise_server_exceptions=False).get(path, params={"q": "Jansen"})
    assert counted == []
