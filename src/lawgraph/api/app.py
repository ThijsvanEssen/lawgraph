from __future__ import annotations

import collections
import logging
import time
import uuid
from collections.abc import Callable
from typing import Annotated

import anyio
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.responses import Response as StarletteResponse

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
    nodes,
    parliament,
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
    API_TRUSTED_PROXIES,
)
from lawgraph.core.logging import setup_logging
from lawgraph.db import ArangoStore

setup_logging()

_logger = logging.getLogger(__name__)

# How long a browser or proxy may use a response without asking again. Short: after a
# migration the new data shows within a minute, and asking again is cheap (``ETag``).
CACHE_TTL_PUBLIC = 60
CACHE_TTL_DEFAULT = 60
# How often the API reads the data version from the database.
DATA_VERSION_TTL = 15.0


class _DataVersion:
    """``ArangoStore.data_version``, read at most every ``DATA_VERSION_TTL`` seconds; None
    while the database cannot be reached."""

    def __init__(self, store: Callable[[], ArangoStore]) -> None:
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

    def __init__(self, app, store: Callable[[], ArangoStore], api_version: str) -> None:
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


class _RateLimitMiddleware:
    """Simple sliding-window rate limiter keyed by client IP.

    Requests originating from our own frontends — i.e. carrying an
    ``Origin`` header that matches ``LAWGRAPH_ALLOWED_ORIGINS`` — bypass
    the limit entirely. The limit still backstops anonymous traffic
    (curl, scrapers, server-to-server abuse).

    Configuration (env vars):
      LAWGRAPH_RATE_LIMIT_CALLS    — max requests per window (default 200)
      LAWGRAPH_RATE_LIMIT_PERIOD   — window in seconds (default 60)
      LAWGRAPH_TRUSTED_PROXIES     — comma-separated IPs that may set
                                     X-Forwarded-For (default loopback only)

    Note: state is stored in-process. With multiple uvicorn workers the
    effective limit is N_workers × LAWGRAPH_RATE_LIMIT_CALLS. Use a
    single worker or an external rate limiter when a hard per-IP cap is
    required.
    """

    _LOOPBACK_PROXIES = frozenset({"127.0.0.1", "::1"})

    def __init__(self, app, *, trusted_origins: frozenset[str]) -> None:
        self._app = app
        self._calls = API_RATE_LIMIT_CALLS
        self._period = API_RATE_LIMIT_PERIOD
        self._trusted_origins = trusted_origins
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
        if hop_ip in trusted_proxies:
            xff = headers.get(b"x-forwarded-for", b"").decode("latin-1").strip()
            if xff:
                # XFF is a comma-separated list; the left-most entry is the
                # original client. Trust it when the hop IP is a known proxy.
                first = xff.split(",", 1)[0].strip()
                if first:
                    return first
        return hop_ip

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        # Bypass for first-party callers: the browser sets Origin and
        # the user can't forge it from a same-origin context, so
        # matching it against the CORS allow-list is a faithful
        # "our own app" check.
        headers = dict(scope.get("headers") or [])
        origin = headers.get(b"origin", b"").decode("latin-1").strip()
        if origin and origin in self._trusted_origins:
            await self._app(scope, receive, send)
            return

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
    version="0.45.0",
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
):
    app.include_router(_router, prefix=f"/api/{_name}", tags=[_name])
app.include_router(feed.atom_router, prefix="/api", tags=["feed"])


@app.middleware("http")
async def _log_requests(request: Request, call_next):
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    response.headers["X-Request-ID"] = request_id
    path = request.url.path
    if request.url.query:
        path = f"{path}?{request.url.query}"
    client = request.client.host if request.client else "-"
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


app.add_middleware(_RateLimitMiddleware, trusted_origins=frozenset(API_ALLOWED_ORIGINS))
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
    allow_credentials=True,
    allow_methods=["GET", "HEAD", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/", tags=["root"])
async def root() -> dict[str, str]:
    """Basic service descriptor used by deployments."""
    return {"name": "lawgraph-api", "version": app.version}


@app.get("/api/health", tags=["root"])
async def health(
    store: Annotated[ArangoStore, Depends(get_store)],
) -> dict[str, str]:
    """Health check — verifies database connectivity."""
    try:
        store.ping()
        return {"status": "ok", "database": "connected"}
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail=f"Database unavailable: {exc}"
        ) from exc


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
