from __future__ import annotations

import faulthandler
import signal
import sys
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.responses import JSONResponse
from starlette.responses import Response as StarletteResponse

from lawgraph import __version__
from lawgraph.api import search_terms
from lawgraph.api.dependencies import get_store
from lawgraph.api.middleware import (
    CacheControlMiddleware,
    CancelOnDisconnectMiddleware,
    RateLimitMiddleware,
    ReadDeadlineMiddleware,
    log_requests,
)
from lawgraph.api.routes import (
    activities,
    annexes,
    articles,
    cabinets,
    commitments,
    committees,
    decisions,
    documents,
    dossiers,
    factions,
    feed,
    instruments,
    judgments,
    lookup,
    members,
    ministries,
    nodes,
    parliament,
    parties,
    paths,
    relationships,
    render,
    resolve,
    search,
    stats,
)
from lawgraph.api.schemas.health import HealthDTO
from lawgraph.api.warm import is_warm, warm_up, warmed_version
from lawgraph.config.settings import (
    ALLOWED_ORIGINS,
    API_HOST,
    API_PORT,
    API_REQUEST_TIMEOUT_MS,
    API_WARM_UP,
    RATE_LIMIT_CALLS,
    RATE_LIMIT_PERIOD,
)
from lawgraph.core.logging import describe, get_logger, setup_logging
from lawgraph.db import GraphStore, version_cache
from lawgraph.db.queries._helpers import busy_calls
from lawgraph.db.queries.not_found import NotFound
from lawgraph.db.request_context import ReadTimedOut, RequestCancelled
from lawgraph.db.schema import CollationMismatch, SchemaOutdated
from lawgraph.db.store import DatabaseUnavailable, close_stores

setup_logging()

_logger = get_logger(__name__)


def _start_warm_up() -> None:
    """Compute what every visitor asks, in the background: now, and after every change of
    the data (``api/warm.py``). A database that cannot be reached is warmed later."""
    if not API_WARM_UP:
        return
    version_cache.on_new_version(warm_up)
    try:
        version_cache.warm(_store(), settle=0)
    except Exception as exc:  # noqa: BLE001 — the API starts without its warm-up
        _logger.warning("No warm-up at the start: %s", describe(exc), exc_info=True)


def _thread_dump_on_signal() -> None:
    """``SIGUSR1`` writes the stack of every thread of the process to stderr (under
    systemd, the journal): ``systemctl kill -s USR1 lawgraph-api`` shows what a hanging
    request waits on. Nothing is written without the signal."""
    if hasattr(signal, "SIGUSR1"):
        faulthandler.register(signal.SIGUSR1, file=sys.stderr, all_threads=True)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """At the start the thread dump on a signal, the warm-up and the flushing of the search
    terms; at the end the search terms written and the pools of the stores closed."""
    _thread_dump_on_signal()
    _start_warm_up()
    await search_terms.start()
    try:
        yield
    finally:
        await search_terms.stop()
        close_stores()


def _store() -> GraphStore:
    """The store of the routes, as a test overrides it (``get_store``)."""
    provide: Callable[[], GraphStore] = app.dependency_overrides.get(
        get_store, get_store
    )
    return provide()


app = FastAPI(
    lifespan=lifespan,
    title="Lawgraph API",
    version=__version__,
    description=(
        "Lawgraph is a FastAPI layer over the PostgreSQL knowledge graph. It "
        "exposes endpoints for articles of law, judgments, parliamentary "
        "dossiers and legislative history."
    ),
)

# What a client paces itself by, in the ``info`` of the schema: how long the API reads for one
# request before it answers 503 (``ReadDeadlineMiddleware``), and how many requests one
# client may make per period (``RateLimitMiddleware``).
_PACE = {
    "x-request-timeout-ms": API_REQUEST_TIMEOUT_MS,
    "x-rate-limit": {"calls": RATE_LIMIT_CALLS, "period_seconds": RATE_LIMIT_PERIOD},
}
_schema = app.openapi


def _openapi() -> dict[str, Any]:
    """The schema of FastAPI (made once), with ``_PACE`` in its ``info``."""
    schema = _schema()
    schema["info"].update(_PACE)
    return schema


app.openapi = _openapi  # type: ignore[method-assign]

# Each module serves the routes under ``/api/<its name>``.
for _module in (
    articles,
    judgments,
    instruments,
    nodes,
    dossiers,
    committees,
    members,
    factions,
    ministries,
    cabinets,
    commitments,
    activities,
    parties,
    relationships,
    annexes,
    documents,
    resolve,
    search,
    stats,
    decisions,
    parliament,
    feed,
    paths,
    lookup,
):
    _name = _module.__name__.rsplit(".", 1)[1]
    app.include_router(_module.router, prefix=f"/api/{_name}", tags=[_name])
app.include_router(feed.atom_router, prefix="/api", tags=["feed"])
# the HTML of every page of Concordans that is no file (Caddy rewrites it to /render)
app.include_router(render.router)


app.middleware("http")(log_requests)
app.add_middleware(ReadDeadlineMiddleware)
app.add_middleware(CancelOnDisconnectMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CacheControlMiddleware,
    store=_store,
    api_version=app.version,
)
# A page of the feed is 87 KB as JSON and some 10 KB compressed; a response under 1 KB is
# sent as it is. A 304 has no body, and the ETag stays weak, so compression leaves both.
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    # no allow_credentials: the API has no cookies and no authentication to send along
    allow_methods=["GET", "HEAD", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/", tags=["root"])
async def root() -> dict[str, str]:
    """Basic service descriptor used by deployments."""
    return {"name": "lawgraph-api", "version": app.version}


@app.get("/api/health", tags=["root"], response_model=HealthDTO)
async def health(
    store: Annotated[GraphStore, Depends(get_store)],
) -> HealthDTO:
    """Health check — verifies database connectivity; ``version`` the version of the API
    (what a deploy checks against its tag). ``warm``: the answers every visitor
    asks are computed for the data as it is now (null when the API does not warm up); a
    deploy waits for true before its smoke test. ``warm_version`` the data version they
    were last computed for (the answers a request gets while a newer one computes, null
    before the first warm-up), ``data_version`` the version now, ``computing`` whether a
    warm-up or an answer of a newer version is being computed. ``pools``: per connection
    pool its size, the free connections and the reads waiting for one; ``busy`` what the
    threads of the shared pools and of the background (the cache, the warm-up) run now,
    and how long."""
    store.ping()
    answer: dict[str, Any] = {
        "status": "ok",
        "version": app.version,
        "database": "connected",
        "warm": None,
    }
    if API_WARM_UP:
        data_version = store.data_version()
        answer |= {
            "warm": is_warm(data_version),
            "warm_version": warmed_version(),
            "data_version": data_version,
            "computing": version_cache.computing(store),
        }
    return HealthDTO.model_validate(
        answer
        | {
            "pools": store.pool_usage(),
            "busy": sorted(
                busy_calls() + version_cache.busy(),
                key=lambda call: -call["seconds"],
            ),
        }
    )


# How long a client waits before it asks again after a read ran past its ceiling, or
# while the database is unavailable.
READ_TIMEOUT_RETRY_AFTER = 30
_RETRY_AFTER = {"Retry-After": str(READ_TIMEOUT_RETRY_AFTER)}


# What a client is told when the database is unavailable, or refused by this version.
_DATABASE_ERRORS: dict[type[Exception], str] = {
    DatabaseUnavailable: "The database is unavailable. Try again later.",
    SchemaOutdated: "The database schema is outdated.",
    CollationMismatch: "The database sorts by another collation.",
}


async def _database_unavailable(request: Request, exc: Exception) -> StarletteResponse:
    """A database the API cannot reach, or one this version refuses: 503 with
    ``Retry-After``; the cause goes to the log, not to the client. A page of ``/render``
    gets no body: Caddy serves the shell of the front end on a 503."""
    _logger.warning("%s %s: %s", request.method, request.url.path, exc)
    if request.url.path.startswith("/render/"):
        return StarletteResponse(status_code=503, headers=_RETRY_AFTER)
    return JSONResponse(
        status_code=503,
        content={"detail": _DATABASE_ERRORS[type(exc)]},
        headers=_RETRY_AFTER,
    )


for _error in _DATABASE_ERRORS:
    app.add_exception_handler(_error, _database_unavailable)


@app.exception_handler(ReadTimedOut)
async def _read_timed_out(request: Request, exc: ReadTimedOut) -> JSONResponse:
    """A query that ran past ``LAWGRAPH_READ_TIMEOUT_MS``: the server is busy, not broken
    (503 with ``Retry-After``, not 500). The statement goes to the log, not to the client.
    A request whose client went away (``RequestCancelled``) is no trouble of the server: it
    is logged as information, and its answer reaches no one."""
    if isinstance(exc, RequestCancelled):
        _logger.info("%s %s: the client went away", request.method, request.url.path)
    else:
        _logger.warning("%s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=503,
        content={"detail": "The query took too long. Try again later, or narrow it."},
        headers=_RETRY_AFTER,
    )


@app.exception_handler(NotFound)
async def _not_found(request: Request, exc: NotFound) -> JSONResponse:
    """What a query or route did not find is a 404; any other error stays a 500."""
    return JSONResponse(status_code=404, content={"detail": str(exc)})


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
