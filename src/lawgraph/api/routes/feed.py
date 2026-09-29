"""The news feed.

GET /api/feed       — dated events of the graph, newest first, filtered, with a cursor
GET /api/feed.atom  — the same page as an Atom feed, for a feed reader
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from lawgraph.api.dependencies import get_store
from lawgraph.api.params import MinistryKey, parse_choices
from lawgraph.api.schemas.feed import (
    FeedFacetsDTO,
    FeedItemDTO,
    FeedResponse,
    atom_feed,
)
from lawgraph.core.feed import FEED_KINDS, FeedCursor
from lawgraph.db import ArangoStore
from lawgraph.db.queries.feed import FeedFilters, get_feed

router = APIRouter()
# Mounted at ``/api``: a path of a router starts with ``/``, and ``feed.atom`` is no
# sub-path of ``/api/feed``.
atom_router = APIRouter()

# A dossier label or the start of one: 36600, 36600-VII, 37020- (its chapters).
DOSSIER_PREFIX_PATTERN = r"^\d+(-[A-Za-z0-9()]*)?$"
ATOM_MEDIA_TYPE = "application/atom+xml"

_EVENTS = (
    "``toezegging`` (a commitment made), ``wetsvoorstel``, ``nota_van_wijziging``, "
    "``amendement``, ``motie`` and ``brief_regering`` (a Tweede Kamer paper submitted), "
    "``stemming`` (a vote with its outcome), ``publicatie`` (in the Staatsblad, "
    "Staatscourant or Tractatenblad) and ``inwerkingtreding`` (a new version of a law in "
    "force)"
)


def feed_filters(
    kind: Annotated[
        str | None,
        Query(description=f"Comma-separated: {', '.join(FEED_KINDS)}."),
    ] = None,
    since: Annotated[dt.date | None, Query(description="On or after this day.")] = None,
    until: Annotated[
        dt.date | None, Query(description="On or before this day.")
    ] = None,
    cabinet: Annotated[
        str | None,
        Query(description="Cabinet key: the events of its period (``jetten``)."),
    ] = None,
    ministry: Annotated[MinistryKey | None, Query()] = None,
    dossier: Annotated[
        str | None,
        Query(
            description="A dossier label or its start: ``36600`` holds ``36600-VII``, "
            "``37020-`` the chapters of 37020.",
            pattern=DOSSIER_PREFIX_PATTERN,
        ),
    ] = None,
    member: Annotated[
        str | None,
        Query(description="Member key: what they signed, the commitments they made."),
    ] = None,
    faction: Annotated[
        str | None,
        Query(description="Faction key: what its Kamerleden signed for it."),
    ] = None,
    q: Annotated[
        str | None,
        Query(
            description="Words of the title, or of the title of the event's dossier, "
            "in any case.",
            max_length=200,
        ),
    ] = None,
) -> FeedFilters:
    """The filters of both feed routes."""
    return FeedFilters(
        kinds=parse_choices(kind, FEED_KINDS, "kind"),
        since=since.isoformat() if since else None,
        until=until.isoformat() if until else None,
        cabinet=cabinet or None,
        ministry=ministry.value if ministry else None,
        dossier=dossier or None,
        member=member or None,
        faction=faction or None,
        q=(q or "").strip() or None,
    )


def _page(
    store: ArangoStore,
    filters: FeedFilters,
    cursor: str | None,
    limit: int,
    facets: bool,
) -> FeedResponse:
    try:
        after = FeedCursor.decode(cursor) if cursor else None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raw = get_feed(store, filters, cursor=after, limit=limit, facets=facets)
    rows = raw.get("items") or []
    page = [FeedItemDTO.from_row(row) for row in rows[:limit]]
    last = page[-1] if len(rows) > limit else None
    return FeedResponse(
        items=page,
        next_cursor=FeedCursor(date=last.date, id=last.id).encode() if last else None,
        total=raw.get("total"),
        facets=FeedFacetsDTO(**raw["facets"]) if raw.get("facets") else None,
    )


_Cursor = Annotated[
    str | None, Query(description="``next_cursor`` of the page before.")
]
_Limit = Annotated[int, Query(ge=1, le=200)]


@router.get(
    "",
    response_model=FeedResponse,
    summary="News feed",
    description=(
        f"What was promised and proposed, as a stream of events, newest first: {_EVENTS}. "
        "Ordered by date, then by ``id``, both descending; ``next_cursor`` gives the next "
        "page, which neither repeats nor skips an event. ``facets`` counts per ``kind``, "
        "``ministry``, ``faction`` and ``cabinet`` the events under the other filters, "
        "with ``total``; ``facets=false`` leaves both out and reads only one page."
    ),
    tags=["feed"],
)
def get_feed_route(
    store: Annotated[ArangoStore, Depends(get_store)],
    filters: Annotated[FeedFilters, Depends(feed_filters)],
    cursor: _Cursor = None,
    limit: _Limit = 50,
    facets: Annotated[
        bool, Query(description="Count the facets and the total.")
    ] = True,
) -> FeedResponse:
    return _page(store, filters, cursor, limit, facets)


@atom_router.get(
    "/feed.atom",
    response_class=Response,
    summary="News feed as Atom",
    description=(
        "A page of ``GET /api/feed`` under the same filters as an Atom 1.0 feed, for a "
        "feed reader: one entry per event, its link the official text or the page on "
        "tweedekamer.nl when it has one, and a ``next`` link to the next page."
    ),
    responses={
        200: {
            "content": {ATOM_MEDIA_TYPE: {"schema": {"type": "string"}}},
            "description": "An Atom 1.0 feed.",
        }
    },
    tags=["feed"],
)
def get_feed_atom(
    request: Request,
    store: Annotated[ArangoStore, Depends(get_store)],
    filters: Annotated[FeedFilters, Depends(feed_filters)],
    cursor: _Cursor = None,
    limit: _Limit = 50,
) -> Response:
    page = _page(store, filters, cursor, limit, facets=False)
    next_url = (
        str(request.url.include_query_params(cursor=page.next_cursor))
        if page.next_cursor
        else None
    )
    body = atom_feed(
        page,
        self_url=str(request.url),
        next_url=next_url,
        node_url=str(request.base_url) + "api/nodes/{collection}/{key}",
    )
    return Response(content=body, media_type=ATOM_MEDIA_TYPE)
