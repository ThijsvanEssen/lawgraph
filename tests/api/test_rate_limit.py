"""The rate limiter counts per client network on a monotonic clock, answers 429 with
Retry-After past the limit and forgets every client whose window has passed."""

from __future__ import annotations

import asyncio

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


def _start(limiter: RateLimitMiddleware, address: str) -> Message:
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
    return sent[0]


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
