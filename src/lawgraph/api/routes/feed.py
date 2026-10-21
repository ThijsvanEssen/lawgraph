"""The news feed.

GET /api/feed          — dated events of the graph, newest first, filtered, with a cursor
GET /api/feed.atom     — the same page as an Atom feed, for a feed reader
GET /api/feed/periods  — the events per month or day under the same filters
"""

from __future__ import annotations

import datetime as dt
from dataclasses import replace
from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request, Response

from lawgraph.api.dependencies import get_store
from lawgraph.api.errors import Invalid
from lawgraph.api.params import (
    DOSSIER_PREFIX_PATTERN,
    LIST_MAX,
    MinistryKey,
    PageLimit,
    parse_choices,
)
from lawgraph.api.schemas.feed import (
    ChamberScheduleDTO,
    FeedFacetsDTO,
    FeedItemDTO,
    FeedPeriodDTO,
    FeedPeriodsResponse,
    FeedResponse,
    FeedSummaryResponse,
    atom_feed,
)
from lawgraph.api.schemas.stats import DataAsOfDTO
from lawgraph.config.constants import Chamber
from lawgraph.config.settings import SITE_URL
from lawgraph.core.coalition import TK_SEATS
from lawgraph.core.courts import TIERS
from lawgraph.core.feed import (
    EVENT_AMENDMENT,
    EVENT_AMENDMENT_NOTE,
    EVENT_BILL,
    EVENT_COMMENCEMENT,
    EVENT_COMMITMENT,
    EVENT_GOVERNMENT_LETTER,
    EVENT_JUDGMENT,
    EVENT_MOTION,
    EVENT_PUBLICATION,
    EVENT_VOTE,
    FEED_KINDS,
    FEED_TIERS,
    FeedCoalition,
    FeedCursor,
    PeriodUnit,
)
from lawgraph.core.identifiers import BWB_ID_PARAM_PATTERN
from lawgraph.core.ministries import MINISTRY_BY_KEY
from lawgraph.core.time import dutch_today, iso_day
from lawgraph.db import GraphStore
from lawgraph.db.queries import feed_events
from lawgraph.db.queries._helpers import COUNTS_BUDGET
from lawgraph.db.queries.activities import get_chamber_schedule
from lawgraph.db.queries.feed import get_feed, get_feed_summary
from lawgraph.db.queries.feed_sql import FeedFilters
from lawgraph.db.queries.stats import cached_data_as_of
from lawgraph.db.request_context import read_budget

router = APIRouter()
# Mounted at ``/api``: a path of a router starts with ``/``, and ``feed.atom`` is no
# sub-path of ``/api/feed``.
atom_router = APIRouter()

ATOM_MEDIA_TYPE = "application/atom+xml"

_EVENTS = (
    "``toezegging`` (a commitment made), ``Voorstel van wet``, ``Nota van wijziging``, "
    "``Amendement``, ``Motie`` and ``Brief regering`` (a Tweede Kamer paper submitted, by "
    "its ``Document.Soort`` before `` (``), "
    "``stemming`` (a vote with its outcome), ``publicatie`` (in the Staatsblad, "
    "Staatscourant or Tractatenblad) and ``inwerkingtreding`` (a new version of a law in "
    "force)"
    " and ``uitspraak`` (a judgment or conclusion, on the day it was published; only "
    "with ``kind=uitspraak`` or ``tier``, of the highest courts and the Parket unless "
    "``tier`` asks for others)"
)


# The words a feed takes in ``q``: how many, and how long each.
MAX_WORDS = 10
MAX_WORD_LENGTH = 200


def _words(q: list[str] | None) -> tuple[str, ...]:
    """The words of ``q``, trimmed, the empty ones left out; 422 for too many or too long."""
    words = tuple(word.strip() for word in q or () if word.strip())
    if len(words) > MAX_WORDS or any(len(word) > MAX_WORD_LENGTH for word in words):
        raise Invalid(
            "q", f"at most {MAX_WORDS} words of {MAX_WORD_LENGTH} characters."
        )
    return words


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
        list[str] | None,
        Query(
            description="Words of the title, or of the title of the event's dossier, "
            "or of a publication the names of the laws it enacts or changes, in any "
            "case: each from the start of a word, one of at most four characters as a "
            f"whole word. Repeat it (at most {MAX_WORDS} times, each "
            f"{MAX_WORD_LENGTH} characters at most) for events that hold any of them; "
            "``matched`` says where each item holds them.",
        ),
    ] = None,
    chamber: Annotated[
        Chamber | None,
        Query(
            description="``EK``: the votes of the Eerste Kamer; ``TK``: the events of the "
            "Tweede Kamer (its papers, votes and commitments). Publications and "
            "commencements belong to neither."
        ),
    ] = None,
    coalition: Annotated[
        FeedCoalition | None,
        Query(
            description="What the coalition did on a vote of the Tweede Kamer: "
            "``together`` (every coalition seat on one side), ``split`` (on both, a "
            "wisselmeerderheid too), ``wissel`` (split, and the side with the most "
            "coalition seats lost), ``decisive`` (the opposition alone would have decided "
            "otherwise). Keeps votes alone."
        ),
    ] = None,
    tier: Annotated[
        str | None,
        Query(
            description="Comma-separated tiers of the judgments (as in "
            "``/api/judgments``): keeps judgments alone. Without it the feed's judgments "
            f"are those of {', '.join(FEED_TIERS)}."
        ),
    ] = None,
    instrument: Annotated[
        str | None,
        Query(
            description="A BWB id: the events tied to that law, each with ``via``: the "
            "publications that enact or change it, the papers that propose to change "
            "it, the events of the dossiers it or a publication of it was legislated in "
            "and of the dossiers of those papers, its new versions and those of the "
            "regulations issued under it, the judgments that cite it.",
            pattern=BWB_ID_PARAM_PATTERN,
        ),
    ] = None,
    article: Annotated[
        str | None,
        Query(
            description="With ``instrument``, an article number of that law (``3:2``): "
            "the events tied to that article; not the dossiers of the law itself, nor "
            "its enactment.",
            max_length=MAX_WORD_LENGTH,
        ),
    ] = None,
) -> FeedFilters:
    """The filters of every feed route but its dates."""
    if article and not instrument:
        raise Invalid("article", "needs `instrument`.")
    return FeedFilters(
        kinds=parse_choices(kind, FEED_KINDS, "kind"),
        cabinet=cabinet or None,
        ministry=ministry.value if ministry else None,
        dossier=dossier or None,
        member=member or None,
        faction=faction or None,
        q=_words(q),
        chamber=chamber,
        tiers=parse_choices(tier, TIERS, "tier"),
        coalition=coalition,
        instrument=instrument.upper() if instrument else None,
        article=(article.strip() or None) if article else None,
    )


def feed_filters(
    scope: Annotated[FeedFilters, Depends(scope_filters)],
    since: Annotated[dt.date | None, Query(description="On or after this day.")] = None,
    until: Annotated[
        dt.date | None, Query(description="On or before this day.")
    ] = None,
) -> FeedFilters:
    """The filters of the feed and its Atom version."""
    return replace(scope, since=iso_day(since), until=iso_day(until))


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
        raise Invalid("cursor", "not one the feed handed out (`next_cursor`).") from exc
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
        partial=bool(raw.get("partial")),
        searched_from=raw.get("searched_from"),
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
        "\n\n"
        "`items`, `next_cursor`, `total`, `facets`, `partial`, `searched_from` and "
        "`data_as_of` (as in `/api/stats`). `total` and `facets` are counted from "
        "`lg_feed_events` (`/api/feed/periods`; as `lawgraph feed-events` last wrote "
        "it: the last 14 days after every poll, every event each night), by its "
        "indexes, each facet as the feed counts it, and kept an hour; under `member`, "
        "`tier` or `instrument`, or before that table is ever written, over every "
        "event under the filters itself. A request waits for them 3 s at most: under "
        "filters not counted before (cold, a minute or more on the full graph) the "
        "page comes at once with both null and `partial` true, and a request after "
        "the count has them. Filters: "
        "`kind` (comma-separated), `since`, `until` (YYYY-MM-DD, inclusive), `cabinet` "
        "(a key: the events from its beëdiging to that of the next cabinet), "
        "`ministry`, `dossier` (the start of a dossier label: `36600` holds "
        "`36600-VII`, `37020-` the chapters), `member` (a member key: the papers they "
        "signed, the votes on them, the commitments they made), `faction` (a faction "
        "key: the papers its Kamerleden signed for it and the votes on them; without "
        "`since` its page is read as under `q`), `q` (words of the title or of "
        "the title of the event's dossier, or of a publication the names of the laws "
        "it changes or enacts and the official title of a law it enacts (from "
        "`lg_feed_events`: a publication is found by them once `lawgraph feed-events` "
        "wrote it), any case; each word from the start of a word, one of at most four "
        "characters as a whole word (`ai`: the AI-verordening, not universitaire; "
        "`stikstof`: Stikstofbank, not natuurstikstof; repeated, at most ten times, "
        "any of them: `q=AI&q=kunstmatige intelligentie`, each event once); each kind "
        "finds them by index where it can (from three characters); without `since` the "
        "page is read once from the first day it reaches back to, the day of the "
        "(`limit` + 1)-th newest matching event in `lg_feed_events` "
        "(`/api/feed/periods`; no later than 14 days ago, what that table may still "
        "lack, nor than the day of the cursor), when that table is written and the "
        "filters are ones it keeps; else, or when that read finds less than the table "
        "counted, the events are searched back from `until`, the cursor or today in "
        "windows of 90 days, a year, three years and then the rest, newest first, "
        "until the page is full or 8 s are spent: then the page has what was found, "
        "`partial` true and `searched_from`, the first day searched, and a request "
        "with `until` the day before goes on; `searched_from` is null when every day "
        "was searched), `tier` (comma-separated tiers as in `/api/judgments`: keeps "
        "judgments alone, of those tiers; without it the feed's judgments are of the "
        "default tiers), `chamber` (`EK`: the votes of the Eerste Kamer, only "
        "the one that decided each bill; `TK`: the papers, votes and commitments of "
        "the Tweede Kamer; publications and commencements are of neither), `coalition` "
        "(what the coalition did on a vote of the Tweede Kamer, as `vote.coalition` "
        "says it: `together`, `split` (on both sides, a wisselmeerderheid too), "
        "`wissel`, `decisive`; keeps votes alone), `instrument` (a BWB id: the events "
        "tied to that law: the publications that enact it or change it or its "
        "articles, the papers that propose to (a `voorgesteld` change), the events of "
        "the dossiers it or such a publication was `LEGISLATED_IN` and of the dossiers "
        "of those papers, its new versions and those of the regulations `BASED_ON` it, "
        "the judgments that cite it; without `since` read as under `q`, in windows; "
        "its total and facets are counted from the events themselves), `article` (with "
        "`instrument`, an article number of that law, `3:2`: the events tied to that "
        "article, the versions of the law that changed it, the dossiers of the "
        "publications and papers that change it, not those of the law itself nor its "
        "enactment; 422 without `instrument`); `limit` (1-200, default 50), `cursor` "
        "(the `next_cursor` of the page before; 422 for a token the API did not hand "
        "out). Order: `date`, newest first; within a day by kind, in the order "
        "`Voorstel van wet`, `stemming`, `toezegging`, `inwerkingtreding`, "
        "`publicatie`, `Nota van wijziging`, `Amendement`, `Motie`, `Brief regering`; "
        "within a kind by `id`. The cursor holds the date, kind and id of the last "
        "event of its page, and a page starts after it, so pages neither repeat nor "
        "skip an event. `facets` (default true) counts per `kind`, `ministry`, "
        "`faction`, `cabinet`, `chamber` (`TK`, `EK`, null for a publication or a "
        "commencement) and `coalition` (the values of the filter; a vote counts for "
        "each that holds, `split` with every `wissel`, an event without a coalition "
        "vote for none) (`{value, count}`, the largest first, `value` null for none) "
        "the events under the other filters, and `total` under all of them, whatever "
        "the cursor; `facets=false` gives null for both and reads one page only, the "
        "choice for the pages after the first. Each item says what it is tied to, read "
        "for the items of the page alone: `matched` (with `q`, per word the event "
        "holds `{term, field}`, `term` as it was asked and `field` the first of "
        "`title` (its own title, of a bill not that of its dossier), `dossier_title` "
        "(the whole title of its first dossier) and `laws` (of a publication, the "
        "names of its laws) that holds it; empty without `q`), `via` (with "
        "`instrument`, how the event is tied to the law: `relation` `establishes`, "
        "`amends`, `introduces` or `repeals` (a publication), `proposes` (a paper with "
        "a `voorgesteld` change of it, or an event of the dossier of such a paper), "
        "`version_of` (a new version of the law), `based_on` (of a regulation issued "
        "under it), `refers_to` (a judgment), `legislated_in` (an event of a dossier "
        "the law or a publication of it was legislated in); `article` the number of "
        "the article of the law it touches, the first in the order of the law; "
        "`dossier` the label of the dossier it came through; the closest tie of all it "
        "has), `answers` (of a `Brief regering`: the motions and commitments it "
        "`ANSWERS`), `answered_by` (of a `toezegging`: the letters that fulfil it), "
        "`replaces` (of a changed `Motie` or `Amendement`: the paper it replaces, "
        '`REVISES`, "ter vervanging van nr. 19"), each such paper or commitment `{id, '
        "kind, title, date, number, dossier, surname, path}` (`kind` its "
        "`Document.Soort` or `toezegging`, `number` its nr. or the number of the "
        "commitment, `dossier` the label of its own dossier, `surname` its first "
        "signatory), at most twenty; `amends_articles` (of an `Amendement`: the "
        "articles it proposes to change, add or repeal, `effect` "
        "`amends`/`introduces`/`repeals`, in the order of their law, at most twenty) "
        "and `cites` (of an `uitspraak`: the articles it cites, the most mentioned "
        "first, at most five), each article `{key, bwb_id, number, law, law_short, "
        "effect, path}`; empty or null for the other kinds"
    ),
    tags=["feed"],
)
def get_feed_route(
    store: Annotated[GraphStore, Depends(get_store)],
    filters: Annotated[FeedFilters, Depends(feed_filters)],
    cursor: _Cursor = None,
    limit: PageLimit = 50,
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
        "\n\n"
        "the same page under the same parameters (without `facets`) as an Atom 1.0 "
        "feed (`application/atom+xml`), named after its filters (`Concordans`, "
        "`Concordans: moties`, `Concordans: dossier 36600`), with an `alternate` link "
        "to the same view on Concordans (`<LAWGRAPH_SITE_URL>/actueel?soort=Motie`: "
        "`soort`, `van`, `tot`, `kabinet`, `ministerie`, `dossier`, `persoon`, "
        "`fractie`, `q` once per word, `kamer`, `coalitie`, `wet`, `artikel`; not the "
        "tier) and a `next` link with the cursor; an entry per event (`id` "
        "`tag:lawgraph,2026:<id>`, `title`, `updated` the date, an `alternate` link to "
        "the event on Concordans (`/explore?focus=<id>`) and a `related` one to its "
        "`official_url` or `tk_url`, `category` its kind, an `author` per person, "
        "`summary` its summary and dossier)"
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
    limit: PageLimit = 50,
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


# How Concordans names the kinds in the plural.
_KIND_PLURALS: dict[str, str] = {
    EVENT_COMMITMENT: "toezeggingen",
    EVENT_BILL: "wetsvoorstellen",
    EVENT_AMENDMENT_NOTE: "nota's van wijziging",
    EVENT_AMENDMENT: "amendementen",
    EVENT_MOTION: "moties",
    EVENT_VOTE: "stemmingen",
    EVENT_PUBLICATION: "publicaties",
    EVENT_COMMENCEMENT: "inwerkingtredingen",
    EVENT_GOVERNMENT_LETTER: "brieven van de regering",
    EVENT_JUDGMENT: "uitspraken",
}
_CHAMBERS = {"TK": "Tweede Kamer", "EK": "Eerste Kamer"}
# The filters as the parameters the page /actueel of Concordans reads.
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
    "coalition": "coalitie",
    "instrument": "wet",
    "article": "artikel",
}
# The coalition value in the words of /actueel.
_SITE_COALITION = {
    "together": "eensgezind",
    "split": "verdeeld",
    "wissel": "wisselmeerderheid",
    "decisive": "doorslaggevend",
}
_COALITION_WORDS = {
    "together": "coalitie eensgezind",
    "split": "coalitie verdeeld",
    "wissel": "wisselmeerderheid",
    "decisive": "coalitie doorslaggevend",
}


def site_query(filters: FeedFilters) -> list[tuple[str, str]]:
    """The filters as the query of the page /actueel of Concordans: the kinds joined by
    commas, each word of ``q`` a parameter of its own."""
    query: list[tuple[str, str]] = []
    for field, parameter in _SITE_PARAMETERS.items():
        value = getattr(filters, field)
        if not value:
            continue
        if field == "q":
            query.extend((parameter, word) for word in value)
        elif field == "coalition":
            query.append((parameter, _SITE_COALITION[value]))
        else:
            query.append(
                (parameter, ",".join(value) if isinstance(value, tuple) else value)
            )
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
    if filters.tiers:  # a tier key in words: ``hoge raad``
        parts.append(" en ".join(tier.replace("_", " ") for tier in filters.tiers))
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
    if filters.coalition:
        parts.append(_COALITION_WORDS[filters.coalition])
    if filters.instrument:
        article = f"artikel {filters.article} " if filters.article else ""
        parts.append(f"{article}{filters.instrument}")
    if filters.q:
        parts.append(" of ".join(f"‘{word}’" for word in filters.q))
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
        "votes decided by at most ``margin`` seats, commitments and commencements; and "
        "``chamber_schedule``: when the Tweede Kamer last met and voted in the plenary "
        "hall and when it meets and votes next (``last_sitting``, ``last_votes``, "
        "``next_sitting``, ``next_votes``), as of today, from its activities "
        "(``Activiteit``): the latest held (``Uitgevoerd``) and the first planned "
        "(``Gepland``), a sitting any plenary kind, the votes ``Stemmingen``; of a week "
        "the one planned for a day before one planned for the week (``precision`` "
        "``Weeknummer``, dated on its Monday); each null when there is none. The Kamer "
        "publishes no recess as data: no sitting planned for days is what tells."
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
            le=TK_SEATS,
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
        int, Query(ge=1, le=LIST_MAX, description="Events shown one by one, at most.")
    ] = 100,
) -> FeedSummaryResponse:
    last = until or dutch_today()
    first = last - dt.timedelta(days=days - 1)
    filters = replace(scope, since=first.isoformat(), until=last.isoformat())
    raw = get_feed_summary(store, filters, margin=margin, few=few, limit=limit)
    summary = FeedSummaryResponse.from_raw(
        raw, since=first, until=last, margin=margin, limit=limit
    )
    summary.data_as_of = _data_as_of(store)
    summary.chamber_schedule = ChamberScheduleDTO.from_raw(
        get_chamber_schedule(store, dutch_today().isoformat())
    )
    return summary


@router.get(
    "/periods",
    response_model=FeedPeriodsResponse,
    summary="News feed per period",
    description=(
        "The events of ``GET /api/feed`` under the same filters, counted per month "
        "(``per=month``) or day (``per=day``, at most "
        f"{feed_events.MAX_DAYS} days from ``since``), per kind: each kind as the feed's "
        "``kind`` facet counts it over those days. Every kind is counted unless ``kind`` "
        "names some. From the events as ``lawgraph feed-events`` last wrote them "
        "(``written_at``: after every poll and every night), not the live graph; not "
        "``member`` and not ``tier``."
        "\n\n"
        "the events of `/api/feed` per period under the same filters (not `member`, "
        "`tier` or `instrument`: 422): `per` `month` (default) or `day` (needs "
        "`since`, at most 400 days to `until`, default today). `{per, since, until, "
        "periods: [{period, total, counts}], partial, written_at, data_as_of}`: "
        "`period` the first day of the month or the day, `counts` per kind (the feed's "
        "kinds) those it has, each as the feed's `kind` facet counts it over those "
        "days; `amendment_chains` (`count`, `aangenomen`, `verworpen`, `other`: "
        "withdrawn, held, postponed, lapsed, not voted yet), the amendments as the "
        "Kamer handles them, unless `kind` leaves them out: each chain of papers that "
        "replace each other (`REVISES`; chains meeting in one last paper are one) "
        "once, when any of its papers is an event under the filters, in the period of "
        "its oldest paper and by the outcome of its last (of its cases the first with "
        "a decision singling it out, of those the latest with an outcome, else the "
        "latest), from `lg_amendment_chains`, written with the events; every kind "
        "unless `kind` names some; a period without events left out, oldest first. "
        "Counted from `lg_feed_events` as `lawgraph feed-events` last wrote it "
        "(`written_at`; after every poll and every night), not from the live graph: "
        "within the budget of the feed's facets (3 s), else `partial` with no periods, "
        "as before the events were ever written"
    ),
    tags=["feed"],
)
def get_feed_periods_route(
    store: Annotated[GraphStore, Depends(get_store)],
    scope: Annotated[FeedFilters, Depends(scope_filters)],
    since: Annotated[dt.date | None, Query(description="On or after this day.")] = None,
    until: Annotated[
        dt.date | None, Query(description="On or before this day.")
    ] = None,
    per: Annotated[PeriodUnit, Query()] = "month",
) -> FeedPeriodsResponse:
    unsupported = feed_events.unsupported(scope)
    if unsupported:
        raise Invalid(tuple(unsupported), "not counted per period.")
    if per == "day":
        last = until or dutch_today()
        if since is None or (last - since).days + 1 > feed_events.MAX_DAYS:
            raise Invalid(
                "since",
                f"needed with `per=day`, at most {feed_events.MAX_DAYS} days before "
                "`until`.",
            )
    # the days of the feed, read as ``feed_filters`` reads them; declared here so the
    # parameters keep their order (``per`` after the days)
    filters = feed_filters(scope, since, until)
    raw: dict[str, Any] = {"periods": [], "written_at": None}
    with read_budget(COUNTS_BUDGET, "The feed per period"):
        raw = feed_events.get_periods(store, filters, per)
    partial = raw["written_at"] is None
    written = raw.get("written_at")
    return FeedPeriodsResponse(
        per=per,
        since=filters.since,
        until=filters.until,
        periods=[] if partial else [FeedPeriodDTO(**p) for p in raw["periods"]],
        partial=partial,
        written_at=written.isoformat() if written else None,
        data_as_of=_data_as_of(store),
    )
