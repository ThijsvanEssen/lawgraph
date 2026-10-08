from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from lawgraph.api import search_terms
from lawgraph.api.dependencies import get_store
from lawgraph.api.routes.resolve import RESOLVE_MAX_LENGTH
from lawgraph.api.schemas.resolve import ResolveResponse
from lawgraph.api.schemas.search import SEARCH_TYPES, SearchResponse, SearchResultItem
from lawgraph.core.logging import get_logger
from lawgraph.db import GraphStore
from lawgraph.db.queries.resolve import NO_MATCH
from lawgraph.db.queries.resolve import resolve as resolve_query
from lawgraph.db.queries.search import LIVE_STALE_WAIT, search_full, search_live
from lawgraph.db.version_cache import STALE_WAIT, stale_wait

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
        "matched on words only (0.1). Hits of a type come best score first. With "
        "`resolve=true` the answer also holds `resolved`, what `/api/resolve` answers "
        "for `q`: one request for a search box that goes to the node a citation names "
        "and lists the hits otherwise."
    ),
    tags=["search"],
)
def search(
    q: Annotated[str, Query(min_length=1, description="Search term")],
    store: Annotated[GraphStore, Depends(get_store)],
    types: Annotated[
        list[str],
        Query(description="Entity types to search"),
    ] = _DEFAULT_SEARCH_TYPES,
    kind: Annotated[
        str | None,
        Query(description="Comma-separated kind filter (documents and dossiers)"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    resolve: Annotated[
        bool, Query(description="Also resolve `q`, as `/api/resolve` does")
    ] = False,
    mode: Annotated[
        Literal["full", "live"],
        Query(
            description=(
                "`live` while typing: all types within 250 ms, cut off types in `partial`, "
                "nothing ranked by its words (a word, or the start of a word of a name or "
                "title), the judgments by ECLI, name and display name (court, date, case number), "
                "the most cited first, and only from three characters; `full` (the "
                "default) ranks everything, a type within 3 s: past it, its `live` hits "
                "and the type in `partial`"
            )
        ),
    ] = "full",
    date_from: Annotated[
        dt.date | None,
        Query(
            alias="from",
            description="Only hits of this day or later, YYYY-MM-DD: by their own date "
            "(a judgment the day it was decided, a paper its date, a dossier the day it "
            "opened, a law the day it came into force and an article that of its law, a "
            "vote and a commitment their day); a faction, committee, cabinet or member "
            "whose period (seats and posts) overlaps.",
        ),
    ] = None,
    date_to: Annotated[
        dt.date | None,
        Query(alias="to", description="Only hits of this day or earlier, as `from`."),
    ] = None,
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
    search_terms.COUNTER.add(q)  # the term alone: who asked is not kept

    kind_list = [s.strip() for s in kind.split(",")] if kind else None

    search = search_live if mode == "live" else search_full
    raw, partial = search(
        store,
        q=q,
        types=requested_types,
        kinds=kind_list,
        limit=limit,
        since=date_from.isoformat() if date_from else None,
        until=date_to.isoformat() if date_to else None,
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
        partial=dict.fromkeys(sorted(partial), True),
        resolved=_resolved(store, q, mode) if resolve else None,
    )


def _resolved(store: GraphStore, q: str, mode: str = "full") -> ResolveResponse:
    """``/api/resolve`` for *q*; a query too long for it is no citation (kind ``none``).
    While typing (``live``) it takes the parser of citations of the version before at once,
    as the search does (``LIVE_STALE_WAIT``)."""
    if len(q) > RESOLVE_MAX_LENGTH:
        return ResolveResponse(q=q, **NO_MATCH)
    wait = LIVE_STALE_WAIT if mode == "live" else STALE_WAIT
    with stale_wait(wait):
        return ResolveResponse(q=q, **resolve_query(store, q))
