from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.queries import search_all
from lawgraph.api.schemas import SEARCH_TYPES, SearchResponse, SearchResultItem
from lawgraph.core.logging import get_logger
from lawgraph.db import ArangoStore

router = APIRouter()
logger = get_logger(__name__)

_DEFAULT_SEARCH_TYPES = sorted(SEARCH_TYPES)


@router.get(
    "",
    response_model=SearchResponse,
    summary="Zoek over meerdere entiteiten",
    description=(
        "Zoekt over artikelen, uitspraken, kamerstukdossiers en publicaties. "
        "Gebruik `types` om te beperken tot specifieke verzamelingen. "
        "Gebruik `soort` om te facetten op publicatie- of dossiertypes."
    ),
    tags=["search"],
)
def search(
    q: Annotated[str, Query(min_length=1, description="Zoekterm")],
    store: Annotated[ArangoStore, Depends(get_store)],
    types: Annotated[
        list[str],
        Query(description="Typen om te zoeken"),
    ] = _DEFAULT_SEARCH_TYPES,
    soort: Annotated[
        str | None,
        Query(description="Kommagescheiden soort-filter (op publicaties en dossiers)"),
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

    soort_list = [s.strip() for s in soort.split(",")] if soort else None

    raw = search_all(
        store,
        q=q,
        types=requested_types,
        soort=soort_list,
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
                    score=1.0,
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
