"""Watch-list endpoints — persist node watches server-side."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from lawgraph.api.dependencies import get_store, require_write_key
from lawgraph.api.queries.watches import create_watch, delete_watch, list_watches
from lawgraph.api.schemas.watches import WatchIn, WatchOut
from lawgraph.core.logging import get_logger
from lawgraph.db import ArangoStore

router = APIRouter()
logger = get_logger(__name__)


@router.get(
    "",
    response_model=list[WatchOut],
    summary="List all watches",
    tags=["watches"],
)
def get_watches(
    store: Annotated[ArangoStore, Depends(get_store)],
) -> list[WatchOut]:
    """Return all saved watches, newest first."""
    return [WatchOut.from_document(doc) for doc in list_watches(store)]


@router.post(
    "",
    response_model=WatchOut,
    status_code=201,
    summary="Add a node to the watchlist",
    description="Requires the X-Write-Key header.",
    tags=["watches"],
    dependencies=[Depends(require_write_key)],
)
def add_watch(
    body: WatchIn,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> WatchOut:
    """Create a new watch for a node."""
    node_id = body.node_id
    if "/" not in node_id:
        raise HTTPException(
            status_code=400,
            detail=f"Node '{node_id}' not found.",
        )
    collection, key = node_id.split("/", 1)
    if (
        not store.db.has_collection(collection)
        or store.db.collection(collection).get(key) is None
    ):
        raise HTTPException(
            status_code=400,
            detail=f"Node '{node_id}' not found.",
        )
    doc = create_watch(
        store,
        node_id=node_id,
        label=body.label,
        collection=body.collection,
    )
    return WatchOut.from_document(doc)


@router.delete(
    "/{watch_id}",
    status_code=204,
    summary="Remove a watch",
    description=(
        "Removes a watch by its ``_key``. Returns HTTP 204 with no body on "
        "success, 404 when the watch does not exist. Requires the X-Write-Key header."
    ),
    tags=["watches"],
    dependencies=[Depends(require_write_key)],
)
def remove_watch(
    watch_id: str,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> None:
    """Delete a watch by its ID."""
    if not delete_watch(store, watch_id):
        raise HTTPException(status_code=404, detail=f"Watch '{watch_id}' not found.")
