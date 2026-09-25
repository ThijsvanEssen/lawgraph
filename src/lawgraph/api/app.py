from __future__ import annotations

import collections
import logging
import time
import uuid
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import Response as StarletteResponse

from lawgraph.api.dependencies import get_store
from lawgraph.api.routes import (
    annexes,
    articles,
    committees,
    decisions,
    documents,
    dossiers,
    government,
    graph,
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

CACHE_TTL_ARTICLES = 1800
CACHE_TTL_JUDGMENTS = 3600
CACHE_TTL_STATS = 300
CACHE_TTL_DEFAULT = 60


class _CacheControlMiddleware:
    """Inject Cache-Control headers on successful GET responses."""

    _RULES: tuple[tuple[str, str], ...] = (
        ("/api/articles/", f"public, max-age={CACHE_TTL_ARTICLES}"),
        ("/api/judgments/", f"public, max-age={CACHE_TTL_JUDGMENTS}"),
        ("/api/stats", f"public, max-age={CACHE_TTL_STATS}"),
    )
    _DEFAULT = f"private, max-age={CACHE_TTL_DEFAULT}"

    def __init__(self, app) -> None:
        self._app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope.get("method") != "GET":
            await self._app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        cache_value = self._DEFAULT
        for prefix, header in self._RULES:
            if path.startswith(prefix):
                cache_value = header
                break

        async def _send_with_cache(message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                status = message.get("status", 200)
                # Only add Cache-Control on 2xx responses
                if 200 <= status < 300:
                    headers.append((b"cache-control", cache_value.encode()))
                    message = {**message, "headers": headers}
            await send(message)

        await self._app(scope, receive, _send_with_cache)


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
    version="0.18.0",
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
    ("graph", graph.router),
    ("relationships", relationships.router),
    ("annexes", annexes.router),
    ("documents", documents.router),
    ("resolve", resolve.router),
    ("search", search.router),
    ("stats", stats.router),
    ("decisions", decisions.router),
    ("parliament", parliament.router),
):
    app.include_router(_router, prefix=f"/api/{_name}", tags=[_name])


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
app.add_middleware(_CacheControlMiddleware)
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
