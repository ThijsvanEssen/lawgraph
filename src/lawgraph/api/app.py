from __future__ import annotations

import collections
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import Response as StarletteResponse

from lawgraph.api.dependencies import get_store
from lawgraph.api.routes import articles, instruments, judgments, nodes
from lawgraph.api.routes.commissies import fracties_router, leden_router
from lawgraph.api.routes.commissies import router as commissies_router
from lawgraph.api.routes.dossiers import party_router
from lawgraph.api.routes.dossiers import router as dossiers_router
from lawgraph.api.routes.graph import router as graph_router
from lawgraph.api.routes.parlement import router as parlement_router
from lawgraph.api.routes.publications import router as publications_router
from lawgraph.api.routes.search import router as search_router
from lawgraph.api.routes.stats import router as stats_router
from lawgraph.api.routes.stemmingen import router as stemmingen_router
from lawgraph.api.routes.watches import router as watches_router
from lawgraph.db import ArangoStore

_logger = logging.getLogger(__name__)


class _CacheControlMiddleware:
    """Inject Cache-Control headers on successful GET responses."""

    _RULES: tuple[tuple[str, str], ...] = (
        ("/api/articles/", "public, max-age=1800"),
        ("/api/judgments/", "public, max-age=3600"),
        ("/api/stats", "public, max-age=300"),
    )
    _DEFAULT = "private, max-age=60"

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
    """

    _LOOPBACK_PROXIES = frozenset({"127.0.0.1", "::1"})

    def __init__(self, app, *, trusted_origins: frozenset[str]) -> None:
        self._app = app
        self._calls: int = int(os.getenv("LAWGRAPH_RATE_LIMIT_CALLS", "200"))
        self._period: float = float(os.getenv("LAWGRAPH_RATE_LIMIT_PERIOD", "60"))
        self._trusted_origins = trusted_origins
        # Trusted proxy hop IPs — only honour X-Forwarded-For when the
        # connection arrives from one of these. Defaults to loopback so
        # local dev + reverse-proxy on same host both work.
        proxies_env = os.getenv("LAWGRAPH_TRUSTED_PROXIES", "")
        custom = {ip.strip() for ip in proxies_env.split(",") if ip.strip()}
        self._trusted_proxies: frozenset[str] = (
            frozenset(custom) | self._LOOPBACK_PROXIES
            if custom
            else self._LOOPBACK_PROXIES
        )
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
        bucket = self._history[ip]

        # Prune old timestamps
        self._history[ip] = [t for t in bucket if t > cutoff]
        if len(self._history[ip]) >= self._calls:
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


@asynccontextmanager
async def _lifespan(application: FastAPI):  # noqa: ARG001
    """Validate environment variables at startup."""
    recommended = {
        "ARANGO_URL": "ArangoDB URL",
        "ARANGO_PASSWORD": "ArangoDB password",
        "LAWGRAPH_ALLOWED_ORIGINS": "CORS allowed origins",
    }
    for var, description in recommended.items():
        if not os.getenv(var):
            _logger.warning(
                "Environment variable %s not set (%s); using default.", var, description
            )
    yield


app = FastAPI(
    title="Lawgraph API",
    version="0.4.0",
    description=(
        "Lawgraph biedt een FastAPI-laag boven de ArangoDB knowledge graph. "
        "De service exposeert endpoints voor wetsartikelen, uitspraken, "
        "parlementaire dossiers en wetgevingsgeschiedenis."
    ),
    lifespan=_lifespan,
)

app.include_router(articles.router, prefix="/api/articles", tags=["articles"])
app.include_router(judgments.router, prefix="/api/judgments", tags=["judgments"])
app.include_router(instruments.router, prefix="/api/instruments", tags=["instruments"])
app.include_router(nodes.router, prefix="/api/nodes", tags=["nodes"])
app.include_router(dossiers_router, prefix="/api/dossiers", tags=["dossiers"])
app.include_router(commissies_router, prefix="/api/commissies", tags=["commissies"])
app.include_router(leden_router, prefix="/api/leden", tags=["leden"])
app.include_router(fracties_router, prefix="/api/fracties", tags=["fracties"])
app.include_router(party_router, prefix="/api/partijen", tags=["partijen"])
app.include_router(graph_router, prefix="/api/graph", tags=["graph"])
app.include_router(
    publications_router, prefix="/api/publications", tags=["publications"]
)
app.include_router(search_router, prefix="/api/search", tags=["search"])
app.include_router(stats_router, prefix="/api/stats", tags=["stats"])
app.include_router(watches_router, prefix="/api/watches", tags=["watches"])
app.include_router(stemmingen_router, prefix="/api/stemmingen", tags=["stemmingen"])
app.include_router(parlement_router, prefix="/api/parlement", tags=["parlement"])

_allowed_origins_env = os.getenv(
    "LAWGRAPH_ALLOWED_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174",
)
origins = [o.strip() for o in _allowed_origins_env.split(",") if o.strip()]


@app.middleware("http")
async def _log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    _logger.info(
        "%s %s → %d (%.1fms)",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # in dev: dit lijstje
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(_CacheControlMiddleware)
app.add_middleware(_RateLimitMiddleware, trusted_origins=frozenset(origins))


@app.get("/", tags=["root"])
async def root() -> dict[str, str]:
    """Basic service descriptor used by deployments."""
    return {"name": "lawgraph-api", "version": app.version}


@app.get("/api/health", tags=["root"])
async def health(store: Annotated[ArangoStore, Depends(get_store)]) -> dict:
    """Health check — verifies database connectivity."""
    try:
        store.db.version()
        return {"status": "ok", "database": "connected"}
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail=f"Database unavailable: {exc}"
        ) from exc
