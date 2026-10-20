from __future__ import annotations

import faulthandler
import signal
import sys
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from lawgraph import __version__
from lawgraph.api import errors, search_terms
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
from lawgraph.db.queries import derive
from lawgraph.db.queries._helpers import busy_calls
from lawgraph.db.store import close_stores

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


def _warn_of_stale_derivations(store: GraphStore) -> None:
    """Log each table whose rows were derived by another derivation than this version's
    (``queries/derive``): its derived columns, which the lists filter and sort on, hold
    what the old one gave until ``semantic graph-derive`` ran over it."""
    for collection in derive.stale_collections(store):
        _logger.warning(
            "The derivation of %s changed: run `lawgraph semantic graph-derive %s`.",
            collection,
            collection,
        )


def _check_derivations() -> None:
    try:
        _warn_of_stale_derivations(_store())
    except Exception as exc:  # noqa: BLE001 — the API starts without the check
        _logger.warning("No check of the derivations: %s", describe(exc))


def _thread_dump_on_signal() -> None:
    """``SIGUSR1`` writes the stack of every thread of the process to stderr (under
    systemd, the journal): ``systemctl kill -s USR1 lawgraph-api`` shows what a hanging
    request waits on. Nothing is written without the signal."""
    if hasattr(signal, "SIGUSR1"):
        faulthandler.register(signal.SIGUSR1, file=sys.stderr, all_threads=True)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """At the start the thread dump on a signal, the tables derived by an older derivation
    named, the warm-up and the flushing of the search terms; at the end the search terms
    written and the pools of the stores closed."""
    _thread_dump_on_signal()
    _check_derivations()
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


# Every error answers ``{"detail": "<a sentence>"}`` (``api/errors.py``), FastAPI's own 422
# too: the schema it names for that answer, in that shape.
_ERROR = {
    "title": "HTTPValidationError",
    "type": "object",
    "properties": {"detail": {"type": "string", "title": "Detail"}},
    "required": ["detail"],
}


def _openapi() -> dict[str, Any]:
    """The schema of FastAPI (made once), with ``_PACE`` in its ``info`` and the shape of
    its errors (``_ERROR``)."""
    schema = _schema()
    schema["info"].update(_PACE)
    schemas = schema["components"]["schemas"]
    schemas["HTTPValidationError"] = _ERROR
    schemas.pop("ValidationError", None)
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
    """Basic service descriptor used by deployments: ``{"name": "lawgraph-api",
    "version": ...}``."""
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
    and how long.

    503 when the database is unreachable. ``warm`` is ``false`` while the warm-up runs,
    also again after a data change; with ``LAWGRAPH_API_WARM_UP=false`` it is null and so
    are ``warm_version``, ``data_version`` and ``computing``. ``pools`` has ``requests``
    and ``background`` (null until it is first needed); ``busy`` names a computation of
    the cache by its kind alone (``cache: <kind>``, never what was asked) and a part of
    the warm-up as ``warm-up: <part>``, longest first. ``pools`` and ``busy`` are read
    from memory."""
    store.ping()
    answer: dict[str, Any] = {
        "status": "ok",
        "version": app.version,
        "database": "connected",
        "warm": None,
    }
    if API_WARM_UP:
        data_version = version_cache.current_version(store)
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


errors.install(app)


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
