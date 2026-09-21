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
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException
from fastapi.routing import APIRoute

from lawgraph.config.settings import curation_api_key, write_api_key
from lawgraph.db import ArangoStore

_store: ArangoStore | None = None

_WRITING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


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


def refuse_open_writes(app: FastAPI) -> None:
    """Raise when a route that writes asks for no key."""
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        writes = sorted(_WRITING_METHODS & set(route.methods or ()))
        asks = any(d.call in _KEYS for d in route.dependant.dependencies)
        if writes and not asks:
            raise RuntimeError(
                f"{'/'.join(writes)} {route.path} asks for no key: add "
                "`dependencies=[Depends(require_write_key)]` (or the curation key)."
            )
