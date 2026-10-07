"""Behind a reverse proxy the rate limit counts the address the proxy saw, not one the
client wrote into X-Forwarded-For; and CORS asks no browser to send credentials."""

from __future__ import annotations

from fastapi.testclient import TestClient

from lawgraph.api.app import _RateLimitMiddleware, app

PROXIES = frozenset({"127.0.0.1", "::1", "10.0.0.2"})


def _ip(hop: str, xff: str | None) -> str:
    headers = {b"x-forwarded-for": xff.encode()} if xff is not None else {}
    return _RateLimitMiddleware._client_ip({"client": (hop, 4711)}, headers, PROXIES)


def test_the_address_our_proxy_appended_counts_not_the_one_the_client_wrote() -> None:
    # Caddy appends the address it was called from to what the client sent
    assert _ip("127.0.0.1", "203.0.113.9") == "203.0.113.9"
    assert _ip("127.0.0.1", "1.2.3.4, 203.0.113.9") == "203.0.113.9"
    assert _ip("127.0.0.1", "1.2.3.4, 5.6.7.8,203.0.113.9") == "203.0.113.9"


def test_proxies_of_our_own_in_the_chain_are_passed_over() -> None:
    assert _ip("127.0.0.1", "1.2.3.4, 203.0.113.9, 10.0.0.2") == "203.0.113.9"
    # only proxies of ours: the hop itself
    assert _ip("127.0.0.1", "10.0.0.2") == "127.0.0.1"


def test_a_client_that_is_no_proxy_is_counted_by_its_own_address() -> None:
    assert _ip("198.51.100.7", "1.2.3.4") == "198.51.100.7"
    assert _ip("127.0.0.1", None) == "127.0.0.1"
    assert _ip("127.0.0.1", " , ") == "127.0.0.1"


def test_cors_allows_the_front_end_and_no_credentials() -> None:
    origin = "http://localhost:5173"
    response = TestClient(app).options(
        "/api/health",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
    )
    assert response.headers.get("access-control-allow-origin") == origin
    assert "access-control-allow-credentials" not in response.headers


def test_a_request_with_the_origin_of_our_front_end_counts_toward_the_limit(
    monkeypatch,
) -> None:
    """Any client can send ``Origin``: it is no pass past the limit."""
    import asyncio

    from lawgraph.api import app as app_module

    monkeypatch.setattr(app_module, "API_RATE_LIMIT_CALLS", 2)
    monkeypatch.setattr(app_module, "API_RATE_LIMIT_PERIOD", 60)

    async def ok(scope, receive, send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    limiter = _RateLimitMiddleware(ok)
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/health",
        "client": ("198.51.100.7", 4711),
        "headers": [(b"origin", b"https://concordans.nl")],
    }

    def status() -> int:
        sent: list[dict] = []

        async def send(message: dict) -> None:
            sent.append(message)

        async def receive() -> dict:
            return {"type": "http.request"}

        asyncio.run(limiter(scope, receive, send))
        return sent[0]["status"]

    assert [status() for _ in range(3)] == [200, 200, 429]
