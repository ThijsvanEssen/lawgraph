"""Watch-list endpoints — persist node watches server-side."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from lawgraph.api.dependencies import get_store
from lawgraph.api.queries import create_watch, delete_watch, list_watches
from lawgraph.core.logging import get_logger
from lawgraph.db import ArangoStore

router = APIRouter()
logger = get_logger(__name__)


class WatchIn(BaseModel):
    """Body for POST /api/watches."""

    model_config = ConfigDict(extra="forbid")

    node_id: str
    label: str | None = None
    collection: str | None = None


class WatchOut(BaseModel):
    """A persisted watch record."""

    model_config = ConfigDict(extra="forbid")

    id: str
    node_id: str
    label: str | None
    collection: str | None
    created_at: str

    @classmethod
    def from_document(cls, doc: dict) -> WatchOut:
        return cls(
            id=doc["_key"],
            node_id=doc["node_id"],
            label=doc.get("label"),
            collection=doc.get("collection"),
            created_at=doc["created_at"],
        )


@router.get(
    "",
    response_model=list[WatchOut],
    summary="Alle watches ophalen",
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
    summary="Node toevoegen aan watchlist",
    tags=["watches"],
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
    summary="Watch verwijderen",
    description=(
        "Verwijdert een watch op zijn ``_key``. Returns HTTP 204 zonder "
        "body bij succes, 404 als de watch niet bestaat."
    ),
    tags=["watches"],
)
def remove_watch(
    watch_id: str,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> None:
    """Delete a watch by its ID."""
    if not delete_watch(store, watch_id):
        raise HTTPException(status_code=404, detail=f"Watch '{watch_id}' not found.")
