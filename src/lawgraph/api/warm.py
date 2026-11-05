"""The answers every visitor asks first, computed before they ask: at the start of the API
and whenever the data version changes (``version_cache.on_new_version``), in the background.
The facets and totals of the unfiltered lists, the statistics and coverage, the
statistics of the search, the lower courts of Actueel, the pages of the newest cabinets,
the dossiers of the active factions, the pages of the most cited laws (judgments, related
laws, EU links) and the dossiers of the homepage; after those the lists under the filters
visitors choose most (``_common_filter_parts``). Off with ``LAWGRAPH_API_WARM_UP=false``."""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from functools import partial
from typing import Any

from lawgraph.api.list_totals import list_totals
from lawgraph.api.routes.dossiers import get_dossier
from lawgraph.api.routes.factions import FACTION_DOSSIER_TABLES, faction_dossiers
from lawgraph.api.routes.instruments import (
    get_instrument_eu_links,
    get_instrument_related_route,
)
from lawgraph.api.routes.stats import coverage_data, stats_data
from lawgraph.config.constants import (
    CHAMBER_EK,
    CHAMBER_TK,
    CHAMBERS,
    COLLECTION_ARTICLES,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_FACTIONS,
    COLLECTION_INSTRUMENT_VERSIONS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    COLLECTION_MEMBERS,
    KIND_TREATY,
)
from lawgraph.config.settings import SEARCH_STATS_DIR
from lawgraph.core import search_stats
from lawgraph.core.logging import describe, get_logger
from lawgraph.core.time import dutch_today, format_duration
from lawgraph.db import GraphStore, version_cache
from lawgraph.db.queries._bm25 import common_share, table_statistics
from lawgraph.db.queries.activities import get_chamber_schedule
from lawgraph.db.queries.articles import (
    most_cited_articles,
)
from lawgraph.db.queries.cabinets import get_cabinet, get_cabinets
from lawgraph.db.queries.chains import warm_most_cited_chains
from lawgraph.db.queries.decisions import DecisionFilters, decision_counts
from lawgraph.db.queries.delegations import (
    TABLES as DELEGATED_TABLES,
)
from lawgraph.db.queries.delegations import (
    count_expired_delegated,
    get_delegated_by_law,
)
from lawgraph.db.queries.documents import list_documents
from lawgraph.db.queries.dossiers import load_dossier_names
from lawgraph.db.queries.factions import get_factions
from lawgraph.db.queries.feed import get_feed, get_feed_summary, get_lower_courts
from lawgraph.db.queries.feed_sql import FeedFilters
from lawgraph.db.queries.instruments import (
    get_citing_judgments,
    get_instruments_list,
    most_cited_laws,
)
from lawgraph.db.queries.judgments import JudgmentFilters, get_judgments_list
from lawgraph.db.queries.law_names import load_law_names
from lawgraph.db.queries.members import load_member_slugs
from lawgraph.db.queries.nodes import (
    NeighborFilter,
    get_node_neighborhood,
)
from lawgraph.db.queries.overlay import IN_FLUX_TABLES, get_in_flux_counts
from lawgraph.db.queries.search.clause import tokenize_search_query
from lawgraph.db.queries.search.dispatch import search_all
from lawgraph.db.queries.search.parser import load_code_aliases, load_notation_parser
from lawgraph.db.queries.search.types import SEARCH_TYPES
from lawgraph.db.queries.stats import cached_data_as_of
from lawgraph.db.queries.warm_nodes import (
    FIRST_PAGES,
    WARM_ARTICLE_CITATIONS,
    WARM_ARTICLES_FIRST,
    warm_articles,
)
from lawgraph.db.schema import SEARCH_FIELDS

logger = get_logger(__name__)

LISTS: dict[str, int] = FIRST_PAGES["lists"]


# The data version the last warm-up was done for (``/api/health`` says whether it is the
# current one).
_warmed: str | None = None


def warmed_version() -> str | None:
    """The data version the last warm-up was done for."""
    return _warmed


def is_warm(data_version: str | None) -> bool:
    """Whether the warm-up is done for the data as it is now (*data_version*; None: not
    known)."""
    return data_version is not None and _warmed == data_version


# The lists of decisions the explorer opens: of both Kamers and of the Tweede Kamer.
FIRST_DECISIONS = (DecisionFilters(), DecisionFilters(chamber="TK"))

# The newest cabinets, whose pages are warmed (each reads every paper its members signed).
WARM_CABINETS = 4


def _warm_cabinets(store: GraphStore) -> None:
    for item in get_cabinets(store)[:WARM_CABINETS]:
        get_cabinet(store, item["cabinet"]["key"])


# The laws with the most citations whose pages are warmed. The Awb and Sr are hundreds of
# thousands of judgments each.
WARM_LAWS = 15


def _warm_law_judgments(store: GraphStore) -> None:
    """The judgments citing each law: the first page as the front end asks it
    (``law_judgments``, the newest first), the next page and the first of the most cited.
    The first reading counts the law once (``get_citing_judgments``), the rest reads a
    page: 24 to 27 s cold for each on prod (28 Oct)."""
    limit = FIRST_PAGES["law_judgments"]
    for bwb_id in most_cited_laws(store, WARM_LAWS):
        get_citing_judgments(store, bwb_id, limit=limit)
        get_citing_judgments(store, bwb_id, limit=limit, offset=limit)
        get_citing_judgments(store, bwb_id, sort="citation_count", limit=limit)


# What Verbonden of a law asks besides its judgments (``RELATED_SHOWN`` and ``EU_LINKS_SHOWN``
# of the explorer): the laws that refer to it (9 s cold for the Awb, 28 Oct) and its European
# and international links, the most important first (4.4 s).
RELATED_SHOWN = 50
EU_LINKS_SHOWN = 50
# How long the links of the laws are read at most (seconds), the most cited first.
LAW_LINKS_FOR = 300.0


def _warm_law_links(store: GraphStore) -> None:
    ends = time.monotonic() + LAW_LINKS_FOR
    for bwb_id in most_cited_laws(store, WARM_LAWS):
        if time.monotonic() >= ends:
            logger.info("Warm-up of the links of laws stopped at %s: its time.", bwb_id)
            return
        get_instrument_related_route(bwb_id, store, RELATED_SHOWN)
        get_instrument_eu_links(bwb_id, store, EU_LINKS_SHOWN, "importance")


# The dossiers of the homepage (those of the events of its summary, the newest day first)
# whose page is warmed (1 to 2.5 s cold on prod, 28 Oct).
WARM_DOSSIERS = 8


def _warm_dossiers(store: GraphStore) -> None:
    summary = get_feed_summary(store, _home_filters(), limit=HOME_SUMMARY["limit"])
    numbers = dict.fromkeys(
        dossier["number"]
        for day in summary.get("days") or []
        for dossier in day.get("dossiers") or []
        if dossier.get("number")
    )
    for number in list(numbers)[:WARM_DOSSIERS]:
        get_dossier(number, store)


def _warm_articles(store: GraphStore, version: str) -> None:
    """The ``WARM_ARTICLES_FIRST`` most cited in full, then the next ones until newer data
    than *version* arrives (no time limit): while this runs, the warm-up of that data
    cannot begin (335 took 21 to 27 minutes on prod)."""
    warm_articles(
        store,
        first=WARM_ARTICLES_FIRST,
        stopped=lambda: version_cache.superseded(store, version),
    )


# The neighbourhood the canvas of the explorer asks of an article (Netwerk tonen in
# Verbonden, the werkplek; ``article_neighborhood``): not kept, but its walk reads the edges
# of every judgment the article's citations reach, which this reads into the memory of the
# database (6:162 BW 7.5 s cold on prod, 0.3 s warm, 27 Oct).
ARTICLE_NEIGHBORHOOD: dict[str, Any] = FIRST_PAGES["article_neighborhood"]
# How long the neighbourhoods of the most cited articles are walked at most (seconds), the
# most cited first: what they read stays in memory only while the database has room.
NEIGHBORHOODS_FOR = 300.0


def _warm_neighborhoods(store: GraphStore) -> None:
    page = ARTICLE_NEIGHBORHOOD
    filters = NeighborFilter(node_types=tuple(page["node_types"]))
    ends = time.monotonic() + NEIGHBORHOODS_FOR
    for article in most_cited_articles(store, WARM_ARTICLE_CITATIONS):
        if time.monotonic() >= ends:
            logger.info(
                "Warm-up of neighbourhoods stopped at %s: its time.", article["key"]
            )
            return
        get_node_neighborhood(
            store,
            COLLECTION_ARTICLES,
            article["key"],
            depth=page["depth"],
            cap=page["cap"],
            filters=filters,
            canvas=page["props"] == "canvas",
            stop_at=tuple(page["stop_at"]),
        )


def _warm_chains(store: GraphStore) -> None:
    """The chains between the most cited articles (``warm_chains``): the edges around
    them are read into the memory of the database, where the nightly's work pushed them
    out."""
    warm_most_cited_chains(store)


# The summary the homepage asks first (its Actueel, ``GET /api/feed/summary``): the last
# ``days`` up to today, ``limit`` events one by one, the margin and few of the route.
HOME_SUMMARY = FIRST_PAGES["home_summary"]


def _home_filters() -> FeedFilters:
    last = dutch_today()
    first = last - dt.timedelta(days=HOME_SUMMARY["days"] - 1)
    return FeedFilters(since=first.isoformat(), until=last.isoformat())


def _warm_home_summary(store: GraphStore) -> None:
    get_feed_summary(store, _home_filters(), limit=HOME_SUMMARY["limit"])
    get_chamber_schedule(store, dutch_today().isoformat())


# The lower courts Actueel asks with its summary (``lower_courts=true``): the judgments of
# the last ``LOWER_COURTS_DAYS`` days up to today (the most the route allows, as Actueel
# opens it on a busy day), counted per day and area of law: 0.9 s cold over 31 days and 6,479
# judgments on prod (29 Oct). Kept per its filters, so only that window is warm.
LOWER_COURTS_DAYS = 31


def _warm_lower_courts(store: GraphStore) -> None:
    last = dutch_today()
    first = last - dt.timedelta(days=LOWER_COURTS_DAYS - 1)
    get_lower_courts(
        store, FeedFilters(since=first.isoformat(), until=last.isoformat())
    )


def _warm_delegated(store: GraphStore) -> None:
    """The regulations in force under the most cited laws, as the explorer asks them
    (``/delegated?detail=summary``): the Awb has 850, 10 s cold."""
    for bwb_id in most_cited_laws(store, WARM_LAWS):
        get_delegated_by_law(store, bwb_id, "in_force", True)
        count_expired_delegated(store, bwb_id)


# The dossiers of the factions of the Tweede Kamer that sit or sat recently, as the explorer
# asks them (Verbonden of a faction: the first 100, newest opened first): each reads every
# paper every member of the faction signed (6 s for the VVD cold on prod, 26 Oct). The page
# is the one Verbonden asks (``DOSSIERS_SHOWN``), in the order the route defaults to.
FACTION_DOSSIERS_LIMIT = 100


def _warm_faction_dossiers(store: GraphStore) -> None:
    for faction in get_factions(store, active=True):
        faction_dossiers(store, faction["id"], FACTION_DOSSIERS_LIMIT, 0, "opened")


@dataclass(frozen=True)
class Part:
    """One part of the warm-up: its name (in the log), what it computes and, for a part
    whose answers are kept per table (``version_cache.cached(tables=...)``), the tables it
    reads. Such a part is left out while its tables stand still, as a poll of judgments
    leaves the instruments; ``tests/pg/test_cached_tables.py`` checks its tables against
    those the plans of its statements read. A part without tables runs on every warm-up;
    one made of parts kept per table (``stats``) finds them kept."""

    name: str
    run: Callable[[GraphStore], object]
    tables: tuple[str, ...] | None = None


_INSTRUMENT_TABLES = (COLLECTION_INSTRUMENTS, COLLECTION_INSTRUMENT_VERSIONS)

# The parts in their order.
PARTS: tuple[Part, ...] = (
    # cheap and asked most first, so that a deploy is warm for them within a minute
    Part("stats", stats_data),
    # the data stand every stats, coverage and feed answer carries (kept a minute)
    Part("data as of", cached_data_as_of),
    # the first call of the homepage
    Part("home summary", _warm_home_summary),
    # the lower courts of Actueel (``lower_courts=true``), before the slow parts after "warm"
    Part("lower courts", _warm_lower_courts),
    # the totals of the lists without a filter (``lists``; each kept per its tables)
    Part("list totals", list_totals),
    Part("coverage", coverage_data, (COLLECTION_JUDGMENTS,)),
    Part("cabinets", _warm_cabinets),
    Part(
        "instruments",
        lambda store: get_instruments_list(
            store, article_count_min=1, limit=LISTS["instruments"]
        ),
        _INSTRUMENT_TABLES,
    ),
    # the names of the largest laws the explorer asks once per visit, when idle
    # (``primeInstrumentNames``)
    Part(
        "instrument names",
        lambda store: get_instruments_list(store, **FIRST_PAGES["instrument_names"]),
        _INSTRUMENT_TABLES,
    ),
    # the facets of the list of laws without a filter, as Bladeren opens it
    # (``?limit=1``, its page asked apart with ``facets=false``)
    Part(
        "instrument facets",
        lambda store: get_instruments_list(store, limit=1),
        _INSTRUMENT_TABLES,
    ),
    Part(
        "documents",
        lambda store: list_documents(store, chambers=("TK",), limit=LISTS["documents"]),
        (COLLECTION_DOCUMENTS,),
    ),
    Part("search notation", load_notation_parser, (COLLECTION_INSTRUMENTS,)),
    Part("search codes", load_code_aliases, (COLLECTION_INSTRUMENTS,)),
    # the laws a dossier title names (``get_laws_named``)
    Part("dossier law names", load_law_names, (COLLECTION_INSTRUMENTS,)),
    Part("dossier names", load_dossier_names, (COLLECTION_DOSSIERS,)),
    Part("member slugs", load_member_slugs, (COLLECTION_MEMBERS,)),
    # the open proposed changes per node, which the explorer asks on every page
    Part("in flux", get_in_flux_counts, IN_FLUX_TABLES),
    *(
        Part(
            f"search {table}",
            partial(table_statistics, table=table),
            (table,),
        )
        for table in SEARCH_FIELDS
    ),
    # as the list opens: of every source, the European among them
    Part(
        "judgments",
        lambda store: get_judgments_list(
            store, JudgmentFilters(), limit=LISTS["judgments"]
        ),
    ),
    # the total and facets of the list of decisions as the explorer opens it, of both
    # Kamers and of the Tweede Kamer (``decision_counts``, kept per version of them)
    Part(
        "decision counts",
        lambda store: [decision_counts(store, filters) for filters in FIRST_DECISIONS],
    ),
    # the feed (its counts from ``lg_feed_events``)
    Part("feed", lambda store: get_feed(store, FeedFilters(), limit=LISTS["feed"])),
    Part(
        "faction dossiers",
        _warm_faction_dossiers,
        (COLLECTION_FACTIONS, *FACTION_DOSSIER_TABLES),
    ),
)
# The long tail, warmed after ``PARTS``: on prod (15 Oct) these took 2 to 5 of the 5 to 8
# minutes to ``warm``. Not beside them: the disk is what a warm-up waits for, and two lanes
# took it from the searches of visitors (16 Oct).
TAIL: tuple[Part, ...] = (
    Part("judgments citing a law", _warm_law_judgments),
    Part("links of laws", _warm_law_links),
    Part("dossiers of the homepage", _warm_dossiers),
    Part("regulations under a law", _warm_delegated, DELEGATED_TABLES),
)
# The version of its tables each of the parts with tables was last warmed for, per
# database, in this process.
_warmed_parts: dict[tuple[str, str], str] = {}


def _warm_lane(store: GraphStore, version: str, parts: tuple[Part, ...]) -> bool:
    """*parts* in their order; whether every one was reached before newer data arrived. The
    first warm-up of the process goes on whatever arrives: during a run the data never
    stands still, and until then the API has no earlier answer to give."""
    for part in parts:
        if version_cache.superseded(store, version) and _warmed is not None:
            # newer data arrived: the warm-up of that version follows once it stands still
            logger.info("Warm-up stopped before %s: the data changed.", part.name)
            return False
        run = partial(part.run, store)
        if part.tables is None:
            _run(part.name, run)
            continue
        # per day too: an answer that names today (``get_delegated_by_law``) is gone at midnight
        stamp = f"{store.data_version(part.tables)}@{dutch_today()}"
        if _warmed_parts.get((store.name, part.name)) == stamp:
            logger.info(
                "Warm-up of %s left: %s did not change.",
                part.name,
                ", ".join(part.tables),
            )
        elif _run(part.name, run):
            _warmed_parts[(store.name, part.name)] = stamp
    return True


def warm_up(store: GraphStore) -> None:
    """Compute what every visitor asks: ``PARTS``, then ``TAIL``, each in its order; each
    part on its own, so one that fails leaves the others, and one whose tables did not
    change since it was warmed left out; then, when both are done, the version it was
    done for is kept (``is_warm``)."""
    global _warmed
    version = store.data_version()
    if not (_warm_lane(store, version, PARTS) and _warm_lane(store, version, TAIL)):
        return
    _warmed = version
    logger.info("Warm-up done: %s.", ", ".join(part.name for part in (*PARTS, *TAIL)))
    # after "warm" (``/api/health``, which a deploy waits for): minutes, and each article
    # is asked far less than the lists above. Without a limit of time, but all of it ends
    # at newer data, whose warm-up cannot begin before this does.
    stopped = partial(version_cache.superseded, store, version)
    if _due("common filters", store.name, COMMON_FILTERS_EVERY):
        _run("common filters", lambda: _warm_common_filters(store, version))
    if not stopped() and _due("most cited articles", store.name, ARTICLES_EVERY):
        for name, part in (
            ("most cited articles", lambda: _warm_articles(store, version)),
            ("most cited neighbourhoods", lambda: _warm_neighborhoods(store)),
            ("chains between the most cited", lambda: _warm_chains(store)),
        ):
            if not stopped():
                _run(name, part)
    if not stopped() and _due("search terms", store.name, SEARCH_TERMS_EVERY):
        _run("search terms", lambda: _warm_search_terms(store))


# The largest values of a facet counted, and the newest years: a small top, whatever the data
# holds. Each tier is counted (``core.courts.TIERS``, a list of its own).
WARM_TOP = 5
WARM_YEARS = 5
# The jurisdictions of the filter of the list of laws (no facet counts them).
_JURISDICTIONS = ("nl", "eu")


def _filter(name: str, count: Callable[..., object], *args: Any, **kwargs: Any) -> Part:
    """A part that counts a list under one filter: *count* with *args* and *kwargs*."""
    return Part(name, lambda store: count(store, *args, **kwargs))


def _values(rows: list[dict[str, Any]] | None) -> list[Any]:
    """The values of the rows of a facet, without the rows that have none."""
    return [row["value"] for row in rows or [] if row.get("value")]


def _judgment_filters(store: GraphStore) -> Iterator[Part]:
    """Each tier, the largest main areas of law, the sources but the largest (nearly the
    whole list, and no list asks it), and the newest years as a bar of the axis asks them."""

    def part(name: str, **filters: Any) -> Part:
        return _filter(name, get_judgments_list, JudgmentFilters(**filters), limit=1)

    facets = get_judgments_list(store, JudgmentFilters(), limit=1)["facets"] or {}
    for tier in _values(facets.get("tier")):
        yield part(f"judgments of {tier}", tiers=(tier,))
    for area in _values(facets.get("subject_area"))[:WARM_TOP]:
        yield part(f"judgments in {area}", subject_area=area)
    for source in _values(facets.get("source"))[1 : WARM_TOP + 1]:
        yield part(f"judgments of {source}", source=source)
    for year in sorted(_values(facets.get("year")), reverse=True)[:WARM_YEARS]:
        whole = {"from_date": f"{year}-01-01", "to_date": f"{year}-12-31"}
        yield part(f"judgments of {year}", **whole)


def _instrument_filters(store: GraphStore) -> Iterator[Part]:
    """As the list of laws opens (with an article): each jurisdiction, the treaties (the
    count beside Verdragen), the largest main areas of law and themes, by the key of their
    concept in the URL (its slug, else its id)."""

    def part(name: str, **filters: Any) -> Part:
        return _filter(
            name, get_instruments_list, article_count_min=1, limit=1, **filters
        )

    opened = get_instruments_list(store, article_count_min=1, limit=1)
    facets = opened["facets"] or {}
    for jurisdiction in _JURISDICTIONS:
        yield part(f"instruments of {jurisdiction}", jurisdiction=jurisdiction)
    yield part("treaties", kind=KIND_TREATY)
    for name in ("legal_area", "policy_domain"):
        concepts = [c.get("slug") or c.get("id") for c in facets.get(name) or []]
        for key in [concept for concept in concepts if concept][:WARM_TOP]:
            yield part(f"instruments of {name} {key}", **{name: key})


def _document_filters(store: GraphStore) -> Iterator[Part]:
    """The Eerste Kamer, both chambers, and the largest kinds of the Tweede Kamer, the list
    as it opens (``documents`` of ``PARTS``)."""

    def part(name: str, chambers: tuple[str, ...], **filters: Any) -> Part:
        return _filter(name, list_documents, chambers=chambers, limit=1, **filters)

    yield part(f"documents of {CHAMBER_EK}", (CHAMBER_EK,))
    yield part("documents of both chambers", CHAMBERS)
    opened = list_documents(store, chambers=(CHAMBER_TK,), limit=1)
    for kind in _values((opened["facets"] or {}).get("kind"))[:WARM_TOP]:
        yield part(f"documents of {CHAMBER_TK}: {kind}", (CHAMBER_TK,), kinds=(kind,))


def _decision_filters(store: GraphStore) -> Iterator[Part]:
    """Of each chamber: its list, its largest kinds and each outcome."""
    for chamber in CHAMBERS:
        base = DecisionFilters(chamber=chamber)
        facets = decision_counts(store, base)["facets"] or {}
        for kind in _values(facets.get("kind"))[:WARM_TOP]:
            filters = replace(base, kinds=(kind,))
            yield _filter(f"decisions of {chamber}: {kind}", decision_counts, filters)
        for passed in (True, False):
            filters = replace(base, passed=passed)
            yield _filter(f"decisions of {chamber}: {passed}", decision_counts, filters)


def _common_filter_parts(store: GraphStore) -> Iterator[Part]:
    """The lists under the filters visitors choose most, the values from the facets of the
    list as ``PARTS`` warmed it, each asked as the explorer asks it (an answer is kept per
    filter); first the lists that count quickly."""
    yield from _decision_filters(store)
    yield from _document_filters(store)
    yield from _instrument_filters(store)
    yield from _judgment_filters(store)


def _warm_common_filters(store: GraphStore, version: str) -> None:
    """One filter at a time until newer data arrives: what was counted is kept, and the next
    warm-up goes on from there, not after ``COMMON_FILTERS_EVERY``."""
    if not _warm_lane(store, version, tuple(_common_filter_parts(store))):
        _last_begun.pop(("common filters", store.name), None)


# The common filters are counted at most once per this many seconds per process, as a wide
# filter holds the workers of the cache for minutes (``tier=rechtbank`` past 3.5 minutes on
# prod, 3 Nov), and a visitor who asks later takes the answer kept while a new one computes,
# however old it is (``version_cache.lasting``).
COMMON_FILTERS_EVERY = 6 * 3600.0
# The most cited articles are warmed at most once per this many seconds per process: the
# lid counts it keeps last as long (``nodes.LIDS_MAX_AGE``), and a poll every half hour
# would start the part of minutes again and again.
ARTICLES_EVERY = 3600.0
# The search of the terms searched most reads the pages of their index and hits into the
# memory of the database, where a warm-up of an hour ago left them also when a poll has
# written since, and keeps their document frequencies per data version (``_bm25``): a
# visitor after a poll gets those of the version before while the new ones compute. So it
# runs at most once per this many seconds per process.
SEARCH_TERMS_EVERY = 3600.0
# per part and database: when the warm-up last began it (monotonic)
_last_begun: dict[tuple[str, str], float] = {}


def _due(part: str, database: str, every: float) -> bool:
    """Whether the warm-up of *database* runs *part* now, begun last *every* seconds ago
    or more; it notes when it does."""
    now = time.monotonic()
    last = _last_begun.get((part, database))
    if last is not None and now - last < every:
        logger.info(
            "Warm-up of %s left: begun %s ago.", part, format_duration(now - last)
        )
        return False
    _last_begun[(part, database)] = now
    return True


def forget() -> None:
    """Forget which parts were warmed and when the parts of every hour began (the
    tests)."""
    global _warmed
    _warmed = None
    _warmed_parts.clear()
    _last_begun.clear()


# The terms searched most in the last ``search_stats.KEEP_DAYS`` days whose search the warm-up
# runs, after everything else: their statistics, the pages of their index and of their
# hits read before the first visitor asks. Only a term asked ``search_stats.MIN_COUNT``
# times or more, as the counts keep them (one asked now and then may name a person).
WARM_SEARCH_TERMS = 5


def _warm_search_terms(store: GraphStore) -> None:
    counts = search_stats.totals(
        SEARCH_STATS_DIR, dutch_today(), search_stats.KEEP_DAYS
    )
    terms = [term for term, n in counts.most_common() if n >= search_stats.MIN_COUNT]
    for term in terms[:WARM_SEARCH_TERMS]:
        words = tokenize_search_query(term)
        if common_share(store, COLLECTION_JUDGMENTS, "summary", words) > COMMON_SHARE:
            continue
        search_all(store, q=term, types=sorted(SEARCH_TYPES), limit=20)


# A term whose judgments are more than this share of them is not searched by the warm-up:
# BM25 ranks every judgment that holds it (``_bm25.common_share`` of their summaries).
COMMON_SHARE = 0.10


def _run(name: str, part: Callable[[], object]) -> bool:
    """One part of the warm-up, logged with how long it took; one that fails leaves the
    others. Whether it was done."""
    logger.info("Warm-up of %s.", name)
    began = time.monotonic()
    try:
        with version_cache.doing(f"warm-up: {name}"):
            part()
    except Exception as exc:  # noqa: BLE001 — the rest is still worth warming
        logger.warning("Warm-up of %s failed: %s", name, describe(exc), exc_info=True)
        return False
    logger.info(
        "Warm-up of %s took %s.", name, format_duration(time.monotonic() - began)
    )
    return True
