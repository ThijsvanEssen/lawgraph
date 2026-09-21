"""Watch-list endpoints."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


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
