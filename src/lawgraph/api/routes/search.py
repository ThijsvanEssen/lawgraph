from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.queries.search import search_all
from lawgraph.api.schemas.search import SEARCH_TYPES, SearchResponse, SearchResultItem
from lawgraph.core.logging import get_logger
from lawgraph.db import ArangoStore

router = APIRouter()
logger = get_logger(__name__)

_DEFAULT_SEARCH_TYPES = sorted(SEARCH_TYPES)


@router.get(
    "",
    response_model=SearchResponse,
    summary="Search across several entity types",
    description=(
        "Searches articles, judgments, dossiers and documents. Use `types` to "
        "restrict the search to specific collections and `kind` to facet on "
        "document or dossier kinds. Every hit has a `score` between 0 and 1, its rank "
        "tier for the query: the query is an identifier of the hit (1), its whole "
        "name (0.75), the start of its name (0.5), part of its name (0.25) or the hit "
        "matched on words only (0.1). Hits of a type come best score first."
    ),
    tags=["search"],
)
def search(
    q: Annotated[str, Query(min_length=1, description="Search term")],
    store: Annotated[ArangoStore, Depends(get_store)],
    types: Annotated[
        list[str],
        Query(description="Entity types to search"),
    ] = _DEFAULT_SEARCH_TYPES,
    kind: Annotated[
        str | None,
        Query(description="Comma-separated kind filter (documents and dossiers)"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> SearchResponse:
    unknown = [t for t in types if t not in SEARCH_TYPES]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown types: {', '.join(sorted(set(unknown)))}. "
                f"Allowed: {', '.join(sorted(SEARCH_TYPES))}."
            ),
        )
    requested_types = types or list(SEARCH_TYPES)

    kind_list = [s.strip() for s in kind.split(",")] if kind else None

    raw = search_all(
        store,
        q=q,
        types=requested_types,
        kinds=kind_list,
        limit=limit,
    )

    grouped: dict[str, list[SearchResultItem]] = {}
    total = 0
    for type_key, hits in raw.items():
        items = []
        for hit in hits:
            items.append(
                SearchResultItem(
                    id=hit.get("id", ""),
                    key=hit.get("key", ""),
                    collection=hit.get("collection", ""),
                    type=hit.get("type", ""),
                    display_name=hit.get("display_name"),
                    snippet=hit.get("snippet"),
                    score=hit["score"],
                    extra=hit.get("extra") or {},
                )
            )
        grouped[type_key] = items
        total += len(items)

    logger.debug("Search '%s' → %d hits across %s", q, total, requested_types)

    return SearchResponse(
        q=q,
        types=requested_types,
        total=total,
        results=grouped,
    )
