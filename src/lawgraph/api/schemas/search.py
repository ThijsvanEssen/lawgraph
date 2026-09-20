"""Search endpoint."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# The collections ``search_all`` can search, named as the collection is.
SEARCH_TYPES = frozenset(
    {
        "articles",
        "instruments",
        "judgments",
        "dossiers",
        "documents",
        "committees",
        "members",
        "factions",
    }
)


class SearchResultItem(BaseModel):
    """One search hit, typed by collection."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    collection: str
    type: str
    display_name: str | None
    snippet: str | None = None
    score: float = 1.0
    extra: dict[str, Any] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    """Full-text search response, grouped by type."""

    model_config = ConfigDict(extra="forbid")

    q: str
    types: list[str]
    total: int
    results: dict[str, list[SearchResultItem]]
