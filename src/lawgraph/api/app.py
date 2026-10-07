from __future__ import annotations

import collections
import ipaddress
import logging
import time
import uuid
from collections.abc import Callable
from typing import Annotated

import anyio
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.responses import JSONResponse
from starlette.responses import Response as StarletteResponse

from lawgraph.api import search_terms
from lawgraph.api.dependencies import get_store
from lawgraph.api.routes import (
    annexes,
    articles,
    committees,
    decisions,
    documents,
    dossiers,
    feed,
    government,
    instruments,
    judgments,
    lookup,
    nodes,
    parliament,
    paths,
    relationships,
    resolve,
    search,
    stats,
)
from lawgraph.config.settings import (
    API_ALLOWED_ORIGINS,
    API_HOST,
    API_PORT,
    API_RATE_LIMIT_CALLS,
    API_RATE_LIMIT_PERIOD,
    API_REQUEST_TIMEOUT_MS,
    API_TRUSTED_PROXIES,
    API_WARM_UP,
)
from lawgraph.core.logging import setup_logging
from lawgraph.db import GraphStore, version_cache
from lawgraph.db.store import (
    ReadTimedOut,
    reset_read_deadline,
    set_read_deadline,
)

setup_logging()

_logger = logging.getLogger(__name__)

# How long a browser or proxy may use a response without asking again. Short: after a
# migration the new data shows within a minute, and asking again is cheap (``ETag``).
CACHE_TTL_PUBLIC = 60
CACHE_TTL_DEFAULT = 60
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
                _logger.warning("No data version: %s: %s", type(exc).__name__, exc)
                self._value = None
            self._read_at = time.monotonic()
        return self._value


class _CacheControlMiddleware:
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
            return f"public, max-age={CACHE_TTL_PUBLIC}"
        return f"private, max-age={CACHE_TTL_DEFAULT}"

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope.get("method") not in ("GET", "HEAD"):
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


class _ReadDeadlineMiddleware:
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
            await self._app(scope, receive, send)
        finally:
            reset_read_deadline(token)


class _RateLimitMiddleware:
    """Simple sliding-window rate limiter keyed by client IP.

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

    def __init__(self, app) -> None:
        self._app = app
        self._calls = API_RATE_LIMIT_CALLS
        self._period = API_RATE_LIMIT_PERIOD
        # X-Forwarded-For is honoured only from these hops; loopback is always trusted so
        # a reverse proxy on the same host works.
        self._trusted_proxies = API_TRUSTED_PROXIES | self._LOOPBACK_PROXIES
        self._history: collections.defaultdict[str, list[float]] = (
            collections.defaultdict(list)
        )

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

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        ip = self._client_ip(scope, headers, self._trusted_proxies)
        now = time.time()
        cutoff = now - self._period

        # Prune stale timestamps; delete the key entirely when empty so the
        # dict doesn't grow unboundedly for long-lived servers with many IPs.
        bucket = self._history.get(ip)
        if bucket is not None:
            pruned = [t for t in bucket if t > cutoff]
            if pruned:
                self._history[ip] = pruned
            else:
                del self._history[ip]

        if len(self._history.get(ip, [])) >= self._calls:
            body = b'{"detail":"Rate limit exceeded. Try again later."}'
            response = StarletteResponse(
                content=body,
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": str(int(self._period))},
            )
            await response(scope, receive, send)
            return

        self._history[ip].append(now)
        await self._app(scope, receive, send)


app = FastAPI(
    title="Lawgraph API",
    version="0.79.4",
    description=(
        "Lawgraph is a FastAPI layer over the ArangoDB knowledge graph. It "
        "exposes endpoints for articles of law, judgments, parliamentary "
        "dossiers and legislative history."
    ),
)

for _name, _router in (
    ("articles", articles.router),
    ("judgments", judgments.router),
    ("instruments", instruments.router),
    ("nodes", nodes.router),
    ("dossiers", dossiers.router),
    ("committees", committees.router),
    ("members", committees.members_router),
    ("factions", committees.factions_router),
    ("ministries", government.ministries_router),
    ("cabinets", government.cabinets_router),
    ("commitments", government.commitments_router),
    ("parties", parliament.party_router),
    ("relationships", relationships.router),
    ("annexes", annexes.router),
    ("documents", documents.router),
    ("resolve", resolve.router),
    ("search", search.router),
    ("stats", stats.router),
    ("decisions", decisions.router),
    ("parliament", parliament.router),
    ("feed", feed.router),
    ("paths", paths.router),
    ("lookup", lookup.router),
):
    app.include_router(_router, prefix=f"/api/{_name}", tags=[_name])
app.include_router(feed.atom_router, prefix="/api", tags=["feed"])


def truncated_ip(host: str) -> str:
    """The network of *host*, not the host: an IPv4 address to its /24 (``203.0.113.0``),
    an IPv6 address to its /48. The full address is in no log line; only the rate limiter
    holds it, in memory. What is no address (``-``, a name) is left as it is."""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host
    prefix = 24 if address.version == 4 else 48
    return str(
        ipaddress.ip_network(f"{address}/{prefix}", strict=False).network_address
    )


@app.middleware("http")
async def _log_requests(request: Request, call_next):
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    response.headers["X-Request-ID"] = request_id
    # the path without its query string (a search term may name a person) and the
    # network of the client, never its address
    path = request.url.path
    client = truncated_ip(request.client.host) if request.client else "-"
    size = response.headers.get("content-length", "-")
    _logger.info(
        "[%s] %s %s %s → %d %sb (%.1fms)",
        request_id[:8],
        client,
        request.method,
        path,
        response.status_code,
        size,
        duration_ms,
    )
    return response


app.add_middleware(_ReadDeadlineMiddleware)
app.add_middleware(_RateLimitMiddleware)
app.add_middleware(
    _CacheControlMiddleware,
    store=lambda: app.dependency_overrides.get(get_store, get_store)(),
    api_version=app.version,
)
# A page of the feed is 87 KB as JSON and some 10 KB compressed; a response under 1 KB is
# sent as it is. A 304 has no body, and the ETag stays weak, so compression leaves both.
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=API_ALLOWED_ORIGINS,
    # no allow_credentials: the API has no cookies and no authentication to send along
    allow_methods=["GET", "HEAD", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/", tags=["root"])
async def root() -> dict[str, str]:
    """Basic service descriptor used by deployments."""
    return {"name": "lawgraph-api", "version": app.version}


@app.get("/api/health", tags=["root"])
async def health(
    store: Annotated[GraphStore, Depends(get_store)],
) -> dict[str, str | bool | None]:
    """Health check — verifies database connectivity. ``warm``: the answers every visitor
    asks are computed for the data as it is now (null when the API does not warm up); a
    deploy waits for true before its smoke test. ``warm_version`` the data version they
    were last computed for (the answers a request gets while a newer one computes, null
    before the first warm-up), ``data_version`` the version now, ``computing`` whether a
    warm-up or an answer of a newer version is being computed."""
    try:
        store.ping()
        if not API_WARM_UP:
            return {"status": "ok", "database": "connected", "warm": None}
        from lawgraph.api.warm import is_warm, warmed_version

        return {
            "status": "ok",
            "database": "connected",
            "warm": is_warm(store),
            "warm_version": warmed_version(),
            "data_version": store.data_version(),
            "computing": version_cache.computing(store),
        }
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail=f"Database unavailable: {exc}"
        ) from exc


def _start_warm_up() -> None:
    """Compute what every visitor asks, in the background: now, and after every change of
    the data (``api/warm.py``). A database that cannot be reached is warmed later."""
    if not API_WARM_UP:
        return
    from lawgraph.api.dependencies import get_store as store_of
    from lawgraph.api.warm import warm_up

    version_cache.on_new_version(warm_up)
    try:
        version_cache.warm(store_of(), settle=0)
    except Exception as exc:  # noqa: BLE001 — the API starts without its warm-up
        _logger.warning("No warm-up at the start: %s: %s", type(exc).__name__, exc)


app.router.on_startup.append(_start_warm_up)
app.router.on_startup.append(search_terms.start)
app.router.on_shutdown.append(search_terms.stop)


# How long a client waits before it asks again after a read ran past its ceiling.
READ_TIMEOUT_RETRY_AFTER = 30


@app.exception_handler(ReadTimedOut)
async def _read_timed_out(request: Request, exc: ReadTimedOut) -> JSONResponse:
    """A query that ran past ``LAWGRAPH_READ_TIMEOUT_MS``: the server is busy, not broken
    (503 with ``Retry-After``, not 500). The statement goes to the log, not to the client."""
    _logger.warning("%s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=503,
        content={"detail": "The query took too long. Try again later, or narrow it."},
        headers={"Retry-After": str(READ_TIMEOUT_RETRY_AFTER)},
    )


def _run_server() -> None:
    """Entry point for the ``lawgraph-api`` CLI script."""
    import uvicorn

    uvicorn.run(
        "lawgraph.api.app:app",
        host=API_HOST,
        port=API_PORT,
        reload=False,
        access_log=False,
    )
