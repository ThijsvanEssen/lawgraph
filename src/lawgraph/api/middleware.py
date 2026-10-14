"""The ASGI middleware of the API: request log, cache headers and ``ETag``, rate limit,
read deadline and cancel on disconnect."""

from __future__ import annotations

import asyncio
import ipaddress
import time
import uuid
from collections.abc import Callable

import anyio
import anyio.to_thread
from fastapi import Request
from starlette.responses import Response as StarletteResponse

from lawgraph.config.settings import (
    API_REQUEST_TIMEOUT_MS,
    RATE_LIMIT_CALLS,
    RATE_LIMIT_PERIOD,
    TRUSTED_PROXIES,
)
from lawgraph.core.logging import describe, get_logger
from lawgraph.db import GraphStore, version_cache
from lawgraph.db.store import (
    Cancellation,
    reset_cancellation,
    reset_read_deadline,
    set_cancellation,
    set_read_deadline,
)

logger = get_logger(__name__)

# How long a browser or proxy may use a response without asking again. Short: after a
# migration the new data shows within a minute, and asking again is cheap (``ETag``).
CACHE_MAX_AGE = 60
# How often the API reads the data version from the database.
DATA_VERSION_TTL = 15.0


class _DataVersion:
    """``GraphStore.data_version``, read at most every ``DATA_VERSION_TTL`` seconds; None
    while the database cannot be reached."""

    def __init__(self, store: Callable[[], GraphStore]) -> None:
        self._store = store
        self._value: str | None = None
        self._read_at = float("-inf")

    async def current(self) -> str | None:
        if time.monotonic() - self._read_at >= DATA_VERSION_TTL:
            try:
                self._value = await anyio.to_thread.run_sync(
                    lambda: self._store().data_version()
                )
            except Exception as exc:  # noqa: BLE001 — no stamp is no cache validation
                logger.warning("No data version: %s", describe(exc))
                self._value = None
            self._read_at = time.monotonic()
        return self._value


class CacheControlMiddleware:
    """An explicit ``Cache-Control`` on every GET and HEAD response (``no-store`` on one
    that is not a success), and on a success a weak ``ETag`` of the API version and the
    data version; a request whose ``If-None-Match`` names the current tag is 304.

    Every response of one API and data version has the same ``ETag``: a cache keeps it per
    URL, and after a migration (a write to the graph) or a release none of them matches
    any more, so a browser that asks again gets the new answer, not a 304 for its old one."""

    _PUBLIC = ("/api/articles/", "/api/judgments/", "/api/stats")

    def __init__(self, app, store: Callable[[], GraphStore], api_version: str) -> None:
        self._app = app
        self._version = _DataVersion(store)
        self._api_version = api_version

    def _cache_value(self, path: str) -> str:
        if path.startswith(self._PUBLIC):
            return f"public, max-age={CACHE_MAX_AGE}"
        return f"private, max-age={CACHE_MAX_AGE}"

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope.get("method") not in ("GET", "HEAD"):
            await self._app(scope, receive, send)
            return
        if scope.get("path", "").startswith("/render/"):
            # a page sets its own: its ETag holds the shell of the front end too
            await self._app(scope, receive, send)
            return

        cache_value = self._cache_value(scope.get("path", ""))
        version = await self._version.current()
        etag = f'W/"{self._api_version}-{version}"'.encode() if version else None
        if etag and etag in _if_none_match(scope):
            headers = [(b"etag", etag), (b"cache-control", cache_value.encode())]
            await send(
                {"type": "http.response.start", "status": 304, "headers": headers}
            )
            await send({"type": "http.response.body", "body": b""})
            return

        async def _send_with_cache(message) -> None:
            if message["type"] == "http.response.start":
                success = 200 <= message.get("status", 200) < 300
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() != b"cache-control"
                ]
                headers.append(
                    (b"cache-control", cache_value.encode() if success else b"no-store")
                )
                if etag and success:
                    headers.append((b"etag", etag))
                message = {**message, "headers": headers}
            await send(message)

        await self._app(scope, receive, _send_with_cache)


def _if_none_match(scope) -> list[bytes]:
    """The entity tags of the request's ``If-None-Match``."""
    return [
        tag.strip()
        for name, value in scope.get("headers", [])
        if name == b"if-none-match"
        for tag in value.split(b",")
    ]


class ReadDeadlineMiddleware:
    """Every request reads the database for at most ``LAWGRAPH_API_REQUEST_TIMEOUT_MS`` in
    all: each statement gets what is left (``store.set_read_deadline``), so a request of
    eight counts does not last eight read ceilings. Past it the request answers 503
    (``ReadTimedOut``)."""

    def __init__(self, app) -> None:
        self._app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        token = set_read_deadline(API_REQUEST_TIMEOUT_MS / 1000)
        try:
            # its waits for new answers share one STALE_WAIT (``version_cache``)
            with version_cache.request_stale_budget():
                await self._app(scope, receive, send)
        finally:
            reset_read_deadline(token)


class CancelOnDisconnectMiddleware:
    """A request whose client went away (a browser that aborts a search at the next
    keystroke) stops reading the database: the reads it runs are cancelled at once, and it
    starts no other (``store.Cancellation``). Without this it read on until its deadline,
    and the search the client did want waited behind it. A computation of the cache it
    started goes on, for the next request."""

    def __init__(self, app) -> None:
        self._app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        cancellation = Cancellation()
        token = set_cancellation(cancellation)
        # every message of the client passes here on its way to the app, so that a
        # disconnect is seen while the app does not read
        messages: asyncio.Queue = asyncio.Queue()

        async def listen() -> None:
            while True:
                message = await receive()
                await messages.put(message)
                if message["type"] == "http.disconnect":
                    # not anyio's to_thread: the server sends this at the end of every
                    # request too, and an anyio worker whose call is cancelled before it
                    # starts (``listening.cancel()``) is never used again but stays
                    await asyncio.to_thread(cancellation.cancel)
                    return

        listening = asyncio.create_task(listen())
        try:
            await self._app(scope, messages.get, send)
        finally:
            listening.cancel()
            reset_cancellation(token)


def _network(host: str, ipv4_prefix: int, ipv6_prefix: int) -> str:
    """The network of *host* with the prefix for its version; what is no address (``-``,
    a name) is left as it is."""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    prefix = ipv4_prefix if address.version == 4 else ipv6_prefix
    return str(
        ipaddress.ip_network(f"{address}/{prefix}", strict=False).network_address
    )


def rate_limit_key(host: str) -> str:
    """Whom the rate limit counts: an IPv4 address, or the /64 of an IPv6 address (one
    subscriber, who can take a new address in it for every request)."""
    return _network(host, ipv4_prefix=32, ipv6_prefix=64)


def truncated_ip(host: str) -> str:
    """The network of *host*, not the host: an IPv4 address to its /24 (``203.0.113.0``),
    an IPv6 address to its /48. The full address is in no log line; only the rate limiter
    holds it (of IPv6 its /64), in memory."""
    return _network(host, ipv4_prefix=24, ipv6_prefix=48)


class RateLimitMiddleware:
    """Sliding-window rate limiter keyed by ``rate_limit_key`` of the client.

    Every request counts, also one with the ``Origin`` of our own front end: any client
    can send that header, and a visitor of the front end has an address of their own.

    Configuration (env vars):
      LAWGRAPH_RATE_LIMIT_CALLS    — max requests per window (default 200)
      LAWGRAPH_RATE_LIMIT_PERIOD   — window in seconds (default 60)
      LAWGRAPH_TRUSTED_PROXIES     — comma-separated IPs that may set
                                     X-Forwarded-For (default loopback only);
                                     its right-most address that is no such
                                     proxy is the client

    Note: state is stored in-process. With multiple uvicorn workers the
    effective limit is N_workers × LAWGRAPH_RATE_LIMIT_CALLS. Use a
    single worker or an external rate limiter when a hard per-IP cap is
    required.
    """

    _LOOPBACK_PROXIES = frozenset({"127.0.0.1", "::1"})

    def __init__(self, app, clock: Callable[[], float] = time.monotonic) -> None:
        self._app = app
        self._clock = clock
        self._calls = RATE_LIMIT_CALLS
        self._period = RATE_LIMIT_PERIOD
        # X-Forwarded-For is honoured only from these hops; loopback is always trusted so
        # a reverse proxy on the same host works.
        self._trusted_proxies = TRUSTED_PROXIES | self._LOOPBACK_PROXIES
        self._history: dict[str, list[float]] = {}
        self._swept_at = clock()

    @staticmethod
    def _client_ip(
        scope, headers: dict[bytes, bytes], trusted_proxies: frozenset[str]
    ) -> str:
        client = scope.get("client")
        hop_ip = client[0] if client else "unknown"
        if hop_ip not in trusted_proxies:
            return hop_ip
        # X-Forwarded-For is a list each proxy appends the address it was called from to.
        # The client writes what it likes at the left, so read from the right: the first
        # address that is no proxy of ours is the one our own proxy saw. (The left-most
        # entry let a made-up header pass the limit as a new client every time.)
        xff = headers.get(b"x-forwarded-for", b"").decode("latin-1")
        hops = [hop.strip() for hop in xff.split(",") if hop.strip()]
        for hop in reversed(hops):
            if hop not in trusted_proxies:
                return hop
        return hop_ip

    def _sweep(self, cutoff: float) -> None:
        """Forget every client without a request inside the window."""
        self._history = {
            key: times
            for key, times in self._history.items()
            if times and times[-1] > cutoff
        }
        self._swept_at = self._clock()

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        key = rate_limit_key(self._client_ip(scope, headers, self._trusted_proxies))
        now = self._clock()
        cutoff = now - self._period
        if now - self._swept_at >= self._period:
            self._sweep(cutoff)

        recent = [t for t in self._history.get(key, ()) if t > cutoff]
        if len(recent) >= self._calls:
            self._history[key] = recent
            body = b'{"detail":"Rate limit exceeded. Try again later."}'
            response = StarletteResponse(
                content=body,
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": str(int(self._period))},
            )
            await response(scope, receive, send)
            return

        self._history[key] = [*recent, now]
        await self._app(scope, receive, send)


async def log_requests(request: Request, call_next):
    """One line per request: its id, the network of the client, the method, the path
    without its query string, the status, the size and how long it took."""
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    start = time.perf_counter()
    # the path without its query string (a search term may name a person) and the
    # network of the client, never its address
    line = (
        f"[{request_id[:8]}] "
        f"{truncated_ip(request.client.host) if request.client else '-'} "
        f"{request.method} {request.url.path} →"
    )
    try:
        response = await call_next(request)
    except Exception:
        # an error no handler answers: the server answers 500, this is its line
        duration_ms = (time.perf_counter() - start) * 1000
        logger.exception("%s 500 (%.1fms)", line, duration_ms)
        raise
    duration_ms = (time.perf_counter() - start) * 1000
    response.headers["X-Request-ID"] = request_id
    size = response.headers.get("content-length", "-")
    logger.info("%s %d %sb (%.1fms)", line, response.status_code, size, duration_ms)
    return response
