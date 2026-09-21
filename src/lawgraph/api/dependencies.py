"""What a route can ask for: the store, and a key before it writes.

Reading is open. Writing is closed unless a key is configured and sent: the write key for
what the community does (watches, votes), the curation key for what a curator does
(tagging a relationship). A key that is not configured closes its routes (HTTP 503): an
API nobody configured writes nothing. ``refuse_open_writes`` runs when the app is built
and refuses a route that writes without asking for one of the two, so forgetting is not
possible.

The keys are shared secrets for a server to send. A browser app cannot keep one: it calls
its own server, which holds the key and passes the request on.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterable, Iterator
from typing import Annotated, Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.routing import APIRoute

from lawgraph.config.settings import curation_api_key, write_api_key
from lawgraph.db import ArangoStore

_store: ArangoStore | None = None

_WRITING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_ROUTE_HOLDERS = ("app", "router", "original_router")


def get_store() -> ArangoStore:
    """Provide an ArangoStore instance for FastAPI routes via Depends."""
    global _store
    if _store is None:
        _store = ArangoStore()
    return _store


def _require(sent: str | None, expected: str | None, variable: str) -> None:
    if not expected:
        raise HTTPException(
            status_code=503,
            detail=f"Writing is not enabled on this deployment ({variable} is not set).",
        )
    if not sent or not secrets.compare_digest(sent, expected):
        raise HTTPException(status_code=401, detail="Missing or invalid key.")


def require_write_key(x_write_key: Annotated[str | None, Header()] = None) -> None:
    """``X-Write-Key``: watches and votes."""
    _require(x_write_key, write_api_key(), "LAWGRAPH_WRITE_API_KEY")


def require_curation_key(
    x_curation_key: Annotated[str | None, Header()] = None,
) -> None:
    """``X-Curation-Key``: what changes the meaning of the graph."""
    _require(x_curation_key, curation_api_key(), "LAWGRAPH_CURATION_API_KEY")


_KEYS = (require_write_key, require_curation_key)


def _api_routes(routes: Iterable[Any]) -> Iterator[APIRoute]:
    """Every API route, also those of a router that is mounted rather than copied in."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
            continue
        # A mounted app, a router, or how FastAPI 0.141 keeps an included router.
        for holder in (route, *(getattr(route, name, None) for name in _ROUTE_HOLDERS)):
            inner = getattr(holder, "routes", None)
            if inner:
                yield from _api_routes(inner)
                break


def _asks_for_a_key(route: APIRoute) -> bool:
    declared = [getattr(d, "dependency", None) for d in route.dependencies]
    resolved = [d.call for d in route.dependant.dependencies]
    return any(call in _KEYS for call in (*declared, *resolved))


def refuse_open_writes(app: FastAPI) -> int:
    """Raise when a route that writes asks for no key; how many writing routes it checked.

    It also raises when it finds no route at all: a check that sees nothing must not pass
    (how a framework stores its routes changes between versions).
    """
    routes = list(_api_routes(app.routes))
    if not routes:
        held = sorted(
            f"{type(route).__module__}.{type(route).__name__}{sorted(vars(route))}"
            for route in app.routes
        )
        raise RuntimeError(
            "refuse_open_writes found no route to check: refusing to start. "
            f"The app holds: {held[:3]}"
        )
    checked = 0
    for route in routes:
        writes = sorted(_WRITING_METHODS & set(route.methods or ()))
        if not writes:
            continue
        checked += 1
        if not _asks_for_a_key(route):
            raise RuntimeError(
                f"{'/'.join(writes)} {route.path} asks for no key: add "
                "`dependencies=[Depends(require_write_key)]` (or the curation key)."
            )
    return checked
