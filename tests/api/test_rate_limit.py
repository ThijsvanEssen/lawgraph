"""The rate limiter counts per client network on a monotonic clock, answers 429 with
Retry-After past the limit (a page to a browser that asks for one), logs each refusal,
leaves the exempt networks alone and forgets every client whose window has passed."""

from __future__ import annotations

import asyncio
import ipaddress
import logging

import pytest
from starlette.types import Message

from lawgraph.api import middleware
from lawgraph.api.middleware import RateLimitMiddleware, rate_limit_key

PERIOD = 60.0


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


async def _ok(scope, receive, send) -> None:
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b""})


def _limiter(monkeypatch, calls: int) -> tuple[RateLimitMiddleware, _Clock]:
    monkeypatch.setattr(middleware, "RATE_LIMIT_CALLS", calls)
    monkeypatch.setattr(middleware, "RATE_LIMIT_PERIOD", PERIOD)
    clock = _Clock()
    return RateLimitMiddleware(_ok, clock=clock), clock


def _start(
    limiter: RateLimitMiddleware, address: str, accept: bytes = b"application/json"
) -> Message:
    return _answer(limiter, address, accept)[0]


def _answer(
    limiter: RateLimitMiddleware, address: str, accept: bytes = b"application/json"
) -> list[Message]:
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
        "headers": [(b"accept", accept)],
    }
    asyncio.run(limiter(scope, receive, send))
    return sent


@pytest.mark.parametrize(
    ("host", "key"),
    [
        ("203.0.113.77", "203.0.113.77"),
        ("2001:db8:1234:5678:aaaa::9", "2001:db8:1234:5678::"),
        ("::ffff:203.0.113.77", "203.0.113.77"),
        ("unknown", "unknown"),
    ],
)
def test_the_key_is_an_ipv4_address_or_an_ipv6_slash_64(host: str, key: str) -> None:
    assert rate_limit_key(host) == key


def test_two_addresses_of_one_ipv6_slash_64_share_a_limit(monkeypatch) -> None:
    limiter, _ = _limiter(monkeypatch, calls=1)
    assert _start(limiter, "2001:db8:1:2::1")["status"] == 200
    assert _start(limiter, "2001:db8:1:2:ffff::7")["status"] == 429
    assert _start(limiter, "2001:db8:1:3::1")["status"] == 200


def test_past_the_limit_a_429_with_retry_after_until_the_window_passes(
    monkeypatch,
) -> None:
    limiter, clock = _limiter(monkeypatch, calls=2)
    assert [_start(limiter, "198.51.100.7")["status"] for _ in range(2)] == [200, 200]
    refused = _start(limiter, "198.51.100.7")
    assert refused["status"] == 429
    assert (b"retry-after", b"60") in refused["headers"]
    clock.now += PERIOD + 1
    assert _start(limiter, "198.51.100.7")["status"] == 200


def test_clients_whose_window_passed_are_forgotten(monkeypatch) -> None:
    limiter, clock = _limiter(monkeypatch, calls=10)
    for n in range(1000):
        _start(limiter, f"10.{n // 256}.{n % 256}.1")
    clock.now += PERIOD + 1
    _start(limiter, "198.51.100.7")
    assert list(limiter._history) == ["198.51.100.7"]


def test_retry_after_is_when_the_oldest_request_leaves_the_window(monkeypatch) -> None:
    limiter, clock = _limiter(monkeypatch, calls=2)
    _start(limiter, "198.51.100.7")
    clock.now += 45
    _start(limiter, "198.51.100.7")
    clock.now += 5
    refused = _start(limiter, "198.51.100.7")
    assert (b"retry-after", b"10") in refused["headers"]


def test_a_browser_asking_for_a_page_gets_a_page_and_the_refusal_is_logged(
    monkeypatch, caplog
) -> None:
    limiter, _ = _limiter(monkeypatch, calls=1)
    _start(limiter, "198.51.100.7")
    with caplog.at_level(logging.INFO, logger=middleware.logger.name):
        start, body = _answer(limiter, "198.51.100.7", b"text/html,*/*;q=0.8")
    assert start["status"] == 429
    assert (b"content-type", b"text/html; charset=utf-8") in start["headers"]
    page = body["body"].decode()
    assert 'content="60"' in page and "60 seconden" in page
    assert "198.51.100.0 GET /api/health → 429" in caplog.text
    assert "198.51.100.7" not in caplog.text
    assert (b"content-type", b"application/json") in _start(limiter, "198.51.100.7")[
        "headers"
    ]


def test_an_exempt_network_is_not_counted(monkeypatch) -> None:
    limiter, _ = _limiter(monkeypatch, calls=1)
    monkeypatch.setattr(
        middleware, "RATE_LIMIT_EXEMPT", (ipaddress.ip_network("192.0.2.0/24"),)
    )
    assert [_start(limiter, "192.0.2.9")["status"] for _ in range(3)] == [200] * 3
    assert [_start(limiter, "198.51.100.7")["status"] for _ in range(2)] == [200, 429]
