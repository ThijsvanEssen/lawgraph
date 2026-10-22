"""The ASGI middleware of the API: request log, cache headers and ``ETag``, rate limit,
read deadline and cancel on disconnect."""

from __future__ import annotations

import asyncio
import concurrent.futures
import ipaddress
import math
import threading
import time
import uuid
from collections.abc import Callable

from fastapi import Request
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response as StarletteResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from lawgraph.api.errors import internal_error
from lawgraph.config.settings import (
    API_REQUEST_TIMEOUT_MS,
    RATE_LIMIT_CALLS,
    RATE_LIMIT_EXEMPT,
    RATE_LIMIT_PERIOD,
    TRUSTED_PROXIES,
)
from lawgraph.core.logging import describe, get_logger
from lawgraph.db import GraphStore, version_cache
from lawgraph.db.request_context import (
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
# The Atom feed: a reader polls it every so often, and its events are written after every
# poll of the sources, not at once.
ATOM_MAX_AGE = 900
# How long a request waits for a new read of the data version when it knows one (seconds):
# past it, it is tagged with the one it knows.
VERSION_WAIT = 0.5


class CacheControlMiddleware:
    """An explicit ``Cache-Control`` on every GET and HEAD response (``no-store`` on one
    that is not a success), and on a success a weak ``ETag`` of the API version and the
    data version; a request whose ``If-None-Match`` names the current tag is 304.

    Every response of one API and data version has the same ``ETag``: a cache keeps it per
    URL, and after a migration (a write to the graph) or a release none of them matches
    any more, so a browser that asks again gets the new answer, not a 304 for its old one.

    The data version, kept ``VERSION_TTL``, is read again on a thread of its own, one read
    at a time, which a request waits for ``VERSION_WAIT`` at most once a version is known:
    never for a free worker of the pool the routes run on. Waiting for one, a
    request waited before its line of the log (``log_requests``) for as long as slow
    routes held every worker (16 Oct: 434 s and 825 s without a line)."""

    _PUBLIC = ("/api/articles/", "/api/judgments/", "/api/stats")

    def __init__(
        self, app: ASGIApp, store: Callable[[], GraphStore], api_version: str
    ) -> None:
        self._app = app
        self._store = store
        self._api_version = api_version
        self._reader = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="lawgraph-version"
        )
        self._lock = threading.RLock()
        # the database of the store, once read, and the read of its version under way
        self._database: str | None = None
        self._reading: concurrent.futures.Future[str | None] | None = None

    def _data_version(self) -> str | None:
        """The data version (``version_cache.current_version``); None while the database
        cannot be reached, and so no tag."""
        try:
            store = self._store()
            self._database = store.name
            return version_cache.current_version(store)
        except Exception as exc:  # noqa: BLE001 — no stamp is no cache validation
            logger.warning("No data version: %s", describe(exc))
            return None

    def _read(self, _: concurrent.futures.Future[str | None]) -> None:
        with self._lock:
            self._reading = None  # the next request past the TTL reads again

    async def _current_version(self) -> str | None:
        """The data version as this process read it less than ``VERSION_TTL`` ago
        (``version_cache.known_version``), else as it reads it now, or, past
        ``VERSION_WAIT``, the one it knows."""
        with self._lock:
            database = self._database
            known = None if database is None else version_cache.known_version(database)
            if known is not None and known[1]:
                return known[0]
            reading = self._reading
            if reading is None:
                reading = self._reading = self._reader.submit(self._data_version)
                # at once, in this thread, when the read is done already
                reading.add_done_callback(self._read)
        waiting = asyncio.shield(asyncio.wrap_future(reading))
        if known is None:
            return await waiting
        try:
            return await asyncio.wait_for(waiting, VERSION_WAIT)
        except TimeoutError:
            return known[0]

    def _cache_value(self, path: str) -> str:
        if path == "/api/feed.atom":
            return f"public, max-age={ATOM_MAX_AGE}"
        if path.startswith(self._PUBLIC):
            return f"public, max-age={CACHE_MAX_AGE}"
        return f"private, max-age={CACHE_MAX_AGE}"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") not in ("GET", "HEAD"):
            await self._app(scope, receive, send)
            return
        if scope.get("path", "").startswith("/render/"):
            # a page sets its own: its ETag holds the shell of the front end too
            await self._app(scope, receive, send)
            return

        cache_value = self._cache_value(scope.get("path", ""))
        version = await self._current_version()
        etag = f'W/"{self._api_version}-{version}"'.encode() if version else None
        if etag and etag in _if_none_match(scope):
            headers = [(b"etag", etag), (b"cache-control", cache_value.encode())]
            await send(
                {"type": "http.response.start", "status": 304, "headers": headers}
            )
            await send({"type": "http.response.body", "body": b""})
            return

        async def _send_with_cache(message: Message) -> None:
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


def _if_none_match(scope: Scope) -> list[bytes]:
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

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
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

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        cancellation = Cancellation()
        token = set_cancellation(cancellation)
        # every message of the client passes here on its way to the app, so that a
        # disconnect is seen while the app does not read
        messages: asyncio.Queue[Message] = asyncio.Queue()

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

    A refused request is a 429 with ``Retry-After`` (the seconds until the oldest request
    of its window leaves it): to a browser that asks for a page (``Accept: text/html``) a
    small page that says so, to any other client the JSON of every error. Each refusal has
    a line in the log, as the request log writes one (the network of the client, the
    path), which it never reaches.

    Configuration (env vars):
      LAWGRAPH_RATE_LIMIT_CALLS    — max requests per window (default 200)
      LAWGRAPH_RATE_LIMIT_PERIOD   — window in seconds (default 60)
      LAWGRAPH_RATE_LIMIT_EXEMPT   — comma-separated addresses or networks
                                     not counted (default none)
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

    def __init__(
        self, app: ASGIApp, clock: Callable[[], float] = time.monotonic
    ) -> None:
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
        scope: Scope, headers: dict[bytes, bytes], trusted_proxies: frozenset[str]
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

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        client = self._client_ip(scope, headers, self._trusted_proxies)
        if _exempt(client):
            await self._app(scope, receive, send)
            return
        key = rate_limit_key(client)
        now = self._clock()
        cutoff = now - self._period
        if now - self._swept_at >= self._period:
            self._sweep(cutoff)

        recent = [t for t in self._history.get(key, ()) if t > cutoff]
        if len(recent) >= self._calls:
            self._history[key] = recent
            retry_after = max(1, math.ceil(recent[0] - cutoff))
            logger.info(
                "%s %s %s → 429 (rate limit)",
                truncated_ip(client),
                scope.get("method", "-"),
                scope.get("path", "-"),
            )
            await _refusal(headers, retry_after)(scope, receive, send)
            return

        self._history[key] = [*recent, now]
        await self._app(scope, receive, send)


def _exempt(client: str) -> bool:
    """Whether *client* is in ``LAWGRAPH_RATE_LIMIT_EXEMPT``."""
    if not RATE_LIMIT_EXEMPT:
        return False
    try:
        address = ipaddress.ip_address(client)
    except ValueError:
        return False
    return any(address in network for network in RATE_LIMIT_EXEMPT)


# What a browser that asks for a page sees when it asked too often: the reason and when to
# come back, and the page asks again by itself then.
_REFUSAL_PAGE = """<!doctype html>
<html lang="nl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="{seconds}">
<title>Even wachten, Concordans</title>
<style>body{{font:1.125rem/1.5 Georgia,serif;max-width:36rem;margin:4rem auto;padding:0 1rem;
color:#1f1f1f;background:#fbfaf7}}@media (prefers-color-scheme:dark){{body{{color:#ece9e2;
background:#191816}}}}</style></head>
<body><h1>Even wachten</h1>
<p>Er kwamen in korte tijd veel verzoeken van dit netwerk. Over {seconds} seconden laadt
deze pagina vanzelf opnieuw.</p></body></html>
"""


def _refusal(headers: dict[bytes, bytes], retry_after: int) -> StarletteResponse:
    """The 429 of the rate limit: a page for a browser that asks for one, else JSON."""
    retry = {"Retry-After": str(retry_after)}
    if b"text/html" in headers.get(b"accept", b""):
        return StarletteResponse(
            content=_REFUSAL_PAGE.format(seconds=retry_after),
            status_code=429,
            media_type="text/html",
            headers=retry,
        )
    return StarletteResponse(
        content=b'{"detail":"Rate limit exceeded. Try again later."}',
        status_code=429,
        media_type="application/json",
        headers=retry,
    )


async def log_requests(
    request: Request, call_next: RequestResponseEndpoint
) -> StarletteResponse:
    """One line per request: its id, the network of the client, the method, the path
    without its query string, the status, the size and how long it took. Every answer
    carries the id as ``X-Request-ID``; an error no handler answers is a 500 with that id
    (``errors.internal_error``), and its line holds the traceback."""
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
    except Exception:  # noqa: BLE001 — an error no handler answers is a 500, logged here
        duration_ms = (time.perf_counter() - start) * 1000
        logger.exception("%s 500 (%.1fms)", line, duration_ms)
        return internal_error(request_id)
    duration_ms = (time.perf_counter() - start) * 1000
    response.headers["X-Request-ID"] = request_id
    size = response.headers.get("content-length", "-")
    logger.info("%s %d %sb (%.1fms)", line, response.status_code, size, duration_ms)
    return response
