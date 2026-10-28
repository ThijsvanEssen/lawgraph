"""Every error of the API in one shape: JSON ``{"detail": "<a sentence>"}``, in English.

- 404 what is not there: ``"<What> '<key>' not found."`` (``NotFound``, and a path no route
  serves).
- 422 a parameter the API cannot answer, from FastAPI's own validation or a check of the
  route (``Invalid``): ``"`param`: what is wrong."``, the parameters first.
- 503 with ``Retry-After``: the database is unavailable or refused, a read ran past its
  ceiling, or what the route reads is not computed yet.
- 500 any other error: ``{"detail": "Internal error.", "request_id": "…"}``, the id of its
  ``X-Request-ID`` header and of its line in the log, which holds the traceback.

No answer names its cause (a statement, a path, a setting): that goes to the log. The API
answers no 400: a value it does not serve is an invalid parameter (422) like any other.
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse
from starlette.responses import Response as StarletteResponse

from lawgraph.core.logging import get_logger
from lawgraph.db.queries._keyset import InvalidCursor
from lawgraph.db.queries.not_found import NotFound
from lawgraph.db.request_context import ReadTimedOut, RequestCancelled
from lawgraph.db.schema import CollationMismatch, SchemaOutdated
from lawgraph.db.store import DatabaseUnavailable

logger = get_logger(__name__)

# How long a client waits before it asks again after a read ran past its ceiling, or
# while the database is unavailable.
READ_TIMEOUT_RETRY_AFTER = 30
RETRY_AFTER = {"Retry-After": str(READ_TIMEOUT_RETRY_AFTER)}

# What a client is told when the database is unavailable, or refused by this version.
_DATABASE_ERRORS: dict[type[Exception], str] = {
    DatabaseUnavailable: "The database is unavailable. Try again later.",
    SchemaOutdated: "The database schema is outdated.",
    CollationMismatch: "The database sorts by another collation.",
}

# The places of a request a parameter is read from (the first part of a pydantic ``loc``).
_PARAMETER_PLACES = ("query", "path", "header", "cookie", "body")


class Invalid(HTTPException):
    """422 for a parameter the route cannot answer: ``"`param`: problem"``, *problem* a
    sentence (with its period) that says what is wrong and, where a choice is closed,
    ``Allowed: …``. Several *params* when the problem is theirs together."""

    def __init__(self, params: str | tuple[str, ...], problem: str) -> None:
        names = (params,) if isinstance(params, str) else params
        named = ", ".join(f"`{name}`" for name in names)
        super().__init__(status_code=422, detail=f"{named}: {problem}")


def internal_error(request_id: str) -> JSONResponse:
    """The answer to an error no handler answers: its id, never its cause."""
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal error.", "request_id": request_id},
        headers={"X-Request-ID": request_id},
    )


def _sentence(text: str) -> str:
    return text if text.endswith(".") else f"{text}."


async def _invalid_request(_: Request, exc: Exception) -> JSONResponse:
    """FastAPI's own validation, in the shape of ``Invalid``: per parameter what pydantic
    says is wrong."""
    assert isinstance(exc, RequestValidationError)
    parts = []
    for error in exc.errors():
        loc = [str(part) for part in error.get("loc", ())]
        name = ".".join(loc[1:] if loc and loc[0] in _PARAMETER_PLACES else loc)
        parts.append(f"`{name or 'request'}`: {_sentence(error['msg'])}")
    return JSONResponse(status_code=422, content={"detail": " ".join(parts)})


async def _no_route(request: Request, _: Exception) -> JSONResponse:
    """A path no route serves, in the shape of ``NotFound``."""
    return JSONResponse(
        status_code=404,
        content={"detail": str(NotFound("Route", request.url.path))},
    )


async def _not_found(_: Request, exc: Exception) -> JSONResponse:
    """What a query or route did not find is a 404; any other error stays a 500."""
    return JSONResponse(status_code=404, content={"detail": str(exc)})


async def _database_unavailable(request: Request, exc: Exception) -> StarletteResponse:
    """A database the API cannot reach, or one this version refuses: 503 with
    ``Retry-After``; the cause goes to the log, not to the client. A page of ``/render``
    gets no body: Caddy serves the shell of the front end on a 503."""
    logger.warning("%s %s: %s", request.method, request.url.path, exc)
    if request.url.path.startswith("/render/"):
        return StarletteResponse(status_code=503, headers=RETRY_AFTER)
    return JSONResponse(
        status_code=503,
        content={"detail": _DATABASE_ERRORS[type(exc)]},
        headers=RETRY_AFTER,
    )


async def _read_timed_out(request: Request, exc: Exception) -> JSONResponse:
    """A query that ran past ``LAWGRAPH_READ_TIMEOUT_MS``: the server is busy, not broken
    (503 with ``Retry-After``, not 500). The statement goes to the log, not to the client.
    A request whose client went away (``RequestCancelled``) is no trouble of the server: it
    is logged as information, and its answer reaches no one."""
    if isinstance(exc, RequestCancelled):
        logger.info("%s %s: the client went away", request.method, request.url.path)
    else:
        logger.warning("%s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=503,
        content={"detail": "The query took too long. Try again later, or narrow it."},
        headers=RETRY_AFTER,
    )


async def _invalid_cursor(request: Request, exc: Exception) -> JSONResponse:
    """An ``after`` that is not the ``next_cursor`` of this list: 422 like any parameter
    that cannot be answered."""
    return JSONResponse(
        status_code=422,
        content={"detail": "`after`: not the `next_cursor` of this list."},
    )


async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
    """An error outside the request log (in a middleware around it): the same 500, logged
    here with its traceback. An error of a route is answered by the request log."""
    request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
    logger.error(
        "[%s] %s %s → 500",
        request_id[:8],
        request.method,
        request.url.path,
        exc_info=exc,
    )
    return internal_error(request_id)


def install(app: FastAPI) -> None:
    """The handlers of every error above on *app*."""
    app.add_exception_handler(RequestValidationError, _invalid_request)
    app.add_exception_handler(NotFound, _not_found)
    app.add_exception_handler(ReadTimedOut, _read_timed_out)
    app.add_exception_handler(InvalidCursor, _invalid_cursor)
    for error in _DATABASE_ERRORS:
        app.add_exception_handler(error, _database_unavailable)
    # Starlette raises a bare 404 for a path no route serves; every 404 of a route is
    # ``NotFound``
    app.add_exception_handler(404, _no_route)
    app.add_exception_handler(Exception, _unexpected)
