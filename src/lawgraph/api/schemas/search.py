"""Search endpoint."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from lawgraph.api.schemas.common import StrictModel, WithPath
from lawgraph.api.schemas.resolve import ResolveResponse


class SearchResultItem(WithPath):
    """One search hit, typed by collection."""

    id: str
    key: str
    collection: str
    type: str
    display_name: str | None
    snippet: str | None = None
    score: float = Field(
        ge=0,
        le=1,
        description="Rank tier of the hit for the query: 1, 0.75, 0.5, 0.25 or 0.1",
    )
    extra: dict[str, Any] = Field(default_factory=dict)


class SearchResponse(StrictModel):
    """Full-text search response, grouped by type."""

    q: str
    types: list[str]
    total: int
    results: dict[str, list[SearchResultItem]]
    partial: dict[str, bool] = Field(
        default_factory=dict,
        description=(
            "With `mode=live`: the types cut off at their budget, `true` each (their "
            "results may be empty or short; the full search has more). A type that was not "
            "cut off is not in it."
        ),
    )
    resolved: ResolveResponse | None = Field(
        default=None,
        description="With `resolve=true`: what `/api/resolve` answers for `q`, in the "
        "same request (kind `none` when nothing fits). Null without it.",
    )
