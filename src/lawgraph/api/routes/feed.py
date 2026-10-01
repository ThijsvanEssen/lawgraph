"""The news feed.

GET /api/feed       — dated events of the graph, newest first, filtered, with a cursor
GET /api/feed.atom  — the same page as an Atom feed, for a feed reader
"""

from __future__ import annotations

import datetime as dt
from dataclasses import replace
from typing import Annotated, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from lawgraph.api.dependencies import get_store
from lawgraph.api.params import MinistryKey, parse_choices
from lawgraph.api.schemas.feed import (
    FeedFacetsDTO,
    FeedItemDTO,
    FeedResponse,
    FeedSummaryResponse,
    atom_feed,
)
from lawgraph.api.schemas.stats import DataAsOfDTO
from lawgraph.config.settings import SITE_URL
from lawgraph.core.feed import FEED_KINDS, FeedCursor
from lawgraph.core.ministries import MINISTRY_BY_KEY
from lawgraph.db import GraphStore
from lawgraph.db.queries.feed import FeedFilters, get_feed, get_feed_summary
from lawgraph.db.queries.stats import cached_data_as_of

router = APIRouter()
# Mounted at ``/api``: a path of a router starts with ``/``, and ``feed.atom`` is no
# sub-path of ``/api/feed``.
atom_router = APIRouter()

# A dossier label or the start of one: 36600, 36600-VII, 37020- (its chapters).
DOSSIER_PREFIX_PATTERN = r"^\d+(-[A-Za-z0-9()]*)?$"
ATOM_MEDIA_TYPE = "application/atom+xml"

_EVENTS = (
    "``toezegging`` (a commitment made), ``Voorstel van wet``, ``Nota van wijziging``, "
    "``Amendement``, ``Motie`` and ``Brief regering`` (a Tweede Kamer paper submitted, by "
    "its ``Document.Soort`` before `` (``), "
    "``stemming`` (a vote with its outcome), ``publicatie`` (in the Staatsblad, "
    "Staatscourant or Tractatenblad) and ``inwerkingtreding`` (a new version of a law in "
    "force)"
)


def scope_filters(
    kind: Annotated[
        str | None,
        Query(description=f"Comma-separated: {', '.join(FEED_KINDS)}."),
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
    chamber: Annotated[
        Literal["TK", "EK"] | None,
        Query(
            description="``EK``: the votes of the Eerste Kamer; ``TK``: the events of the "
            "Tweede Kamer (its papers, votes and commitments). Publications and "
            "commencements belong to neither."
        ),
    ] = None,
) -> FeedFilters:
    """The filters of every feed route but its dates."""
    return FeedFilters(
        kinds=parse_choices(kind, FEED_KINDS, "kind"),
        cabinet=cabinet or None,
        ministry=ministry.value if ministry else None,
        dossier=dossier or None,
        member=member or None,
        faction=faction or None,
        q=(q or "").strip() or None,
        chamber=chamber,
    )


def feed_filters(
    scope: Annotated[FeedFilters, Depends(scope_filters)],
    since: Annotated[dt.date | None, Query(description="On or after this day.")] = None,
    until: Annotated[
        dt.date | None, Query(description="On or before this day.")
    ] = None,
) -> FeedFilters:
    """The filters of the feed and its Atom version."""
    return replace(
        scope,
        since=since.isoformat() if since else None,
        until=until.isoformat() if until else None,
    )


def _page(
    store: GraphStore,
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
        next_cursor=FeedCursor(date=last.date, kind=last.kind, id=last.id).encode()
        if last
        else None,
        total=raw.get("total"),
        facets=FeedFacetsDTO(**raw["facets"]) if raw.get("facets") else None,
        data_as_of=_data_as_of(store),
    )


def _data_as_of(store: GraphStore) -> dict[str, DataAsOfDTO]:
    """How current each source is, as ``GET /api/stats`` says."""
    return {
        source: DataAsOfDTO(**row) for source, row in cached_data_as_of(store).items()
    }


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
    store: Annotated[GraphStore, Depends(get_store)],
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
        "feed reader, named after its filters (``Concordans: moties``): an ``alternate`` "
        "link to the same view on Concordans (``LAWGRAPH_SITE_URL``/actueel), per entry "
        "an ``alternate`` link to the event there and a ``related`` link to its official "
        "page, and a ``next`` link to the next page."
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
    store: Annotated[GraphStore, Depends(get_store)],
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
    query = urlencode(site_query(filters))
    body = atom_feed(
        page,
        title=feed_title(filters, page),
        self_url=str(request.url),
        next_url=next_url,
        page_url=f"{SITE_URL}/actueel" + (f"?{query}" if query else ""),
        site_url=SITE_URL,
    )
    return Response(content=body, media_type=ATOM_MEDIA_TYPE)


# How Concordans names the kinds in the plural, and the parameters of its page /actueel.
_KIND_PLURALS = {
    "toezegging": "toezeggingen",
    "Voorstel van wet": "wetsvoorstellen",
    "Nota van wijziging": "nota's van wijziging",
    "Amendement": "amendementen",
    "Motie": "moties",
    "stemming": "stemmingen",
    "publicatie": "publicaties",
    "inwerkingtreding": "inwerkingtredingen",
    "Brief regering": "brieven van de regering",
}
_CHAMBERS = {"TK": "Tweede Kamer", "EK": "Eerste Kamer"}
_SITE_PARAMETERS = {
    "kinds": "soort",
    "since": "van",
    "until": "tot",
    "cabinet": "kabinet",
    "ministry": "ministerie",
    "dossier": "dossier",
    "member": "persoon",
    "faction": "fractie",
    "q": "q",
    "chamber": "kamer",
}


def site_query(filters: FeedFilters) -> dict[str, str]:
    """The filters as the parameters of the page /actueel of Concordans."""
    query = {}
    for field, parameter in _SITE_PARAMETERS.items():
        value = getattr(filters, field)
        if value:
            query[parameter] = ",".join(value) if isinstance(value, tuple) else value
    return query


def _person_name(page: FeedResponse, key: str) -> str:
    names = (p.name for item in page.items for p in item.persons if p.key == key)
    return next((name for name in names if name), key)


def _faction_name(page: FeedResponse, key: str) -> str:
    shorts = (
        p.faction.short
        for item in page.items
        for p in item.persons
        if p.faction and p.faction.key == key
    )
    return next((short for short in shorts if short), key)


def feed_title(filters: FeedFilters, page: FeedResponse) -> str:
    """``Concordans``, and what the filters keep: ``Concordans: moties, dossier 36600``. A
    person and a faction are named as the page names them."""
    parts = []
    if filters.chamber:
        parts.append(_CHAMBERS[filters.chamber])
    if filters.kinds:
        parts.append(" en ".join(_KIND_PLURALS[kind] for kind in filters.kinds))
    if filters.dossier:
        parts.append(f"dossier {filters.dossier}")
    if filters.ministry:
        ministry = MINISTRY_BY_KEY.get(filters.ministry)
        parts.append(ministry.name if ministry else filters.ministry)
    if filters.cabinet:
        parts.append(f"kabinet {filters.cabinet}")
    if filters.member:
        parts.append(_person_name(page, filters.member))
    if filters.faction:
        parts.append(_faction_name(page, filters.faction))
    if filters.q:
        parts.append(f"‘{filters.q}’")
    if filters.since:
        parts.append(f"vanaf {filters.since}")
    if filters.until:
        parts.append(f"tot en met {filters.until}")
    return "Concordans: " + ", ".join(parts) if parts else "Concordans"


@router.get(
    "/summary",
    response_model=FeedSummaryResponse,
    summary="News feed summary",
    description=(
        "The days up to ``until`` (default today, ``days`` of them) in one small answer, "
        "under the filters of ``GET /api/feed``: per day the events per kind, per dossier "
        "and, of the votes, per subkind and outcome; and the events a timeline shows one by "
        "one, as feed items in the order of the feed: bills submitted, votes on a bill, "
        "votes decided by at most ``margin`` seats, commitments and commencements."
    ),
    tags=["feed"],
)
def get_feed_summary_route(
    store: Annotated[GraphStore, Depends(get_store)],
    scope: Annotated[FeedFilters, Depends(scope_filters)],
    until: Annotated[
        dt.date | None, Query(description="The last day; default today.")
    ] = None,
    days: Annotated[int, Query(ge=1, le=31, description="How many days.")] = 3,
    margin: Annotated[
        int,
        Query(
            ge=0,
            le=150,
            description="A vote this close (seats for minus against) "
            "is shown one by one.",
        ),
    ] = 10,
    few: Annotated[
        int,
        Query(
            ge=0,
            le=50,
            description="Every vote of a day with at most this many votes on "
            "anything but a bill is shown one by one.",
        ),
    ] = 2,
    limit: Annotated[
        int, Query(ge=1, le=500, description="Events shown one by one, at most.")
    ] = 100,
) -> FeedSummaryResponse:
    last = until or dt.date.today()
    first = last - dt.timedelta(days=days - 1)
    filters = replace(scope, since=first.isoformat(), until=last.isoformat())
    raw = get_feed_summary(store, filters, margin=margin, few=few, limit=limit)
    summary = FeedSummaryResponse.from_raw(
        raw, since=first, until=last, margin=margin, limit=limit
    )
    summary.data_as_of = _data_as_of(store)
    return summary
