"""The answers every visitor asks first, computed before they ask: at the start of the API
and whenever the data version changes (``version_cache.on_new_version``), in the background.
The facets and totals of the unfiltered lists, the statistics and coverage, the
statistics of the search, the pages of the newest cabinets and the first page of the
judgments of the largest areas of law. Off with
``LAWGRAPH_API_WARM_UP=false``."""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import Callable
from dataclasses import replace
from functools import partial

from lawgraph.api.routes.stats import coverage_data, stats_data
from lawgraph.api.schemas.search import SEARCH_TYPES
from lawgraph.config.constants import (
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_EDGES,
    COLLECTION_INSTRUMENT_VERSIONS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    COLLECTION_MEMBERS,
)
from lawgraph.config.settings import SEARCH_STATS_DIR
from lawgraph.core import search_stats
from lawgraph.core.logging import get_logger
from lawgraph.core.time import format_duration
from lawgraph.db import GraphStore, version_cache
from lawgraph.db.queries import _bm25
from lawgraph.db.queries._bm25 import _stats as search_statistics
from lawgraph.db.queries.articles import get_article_cited_by, most_cited_articles
from lawgraph.db.queries.cabinets import get_cabinet, get_cabinets
from lawgraph.db.queries.committees import load_member_slugs
from lawgraph.db.queries.decisions import DecisionFilters, decision_counts
from lawgraph.db.queries.documents import list_documents
from lawgraph.db.queries.dossiers import load_dossier_names, load_law_names
from lawgraph.db.queries.feed import FeedFilters, get_feed
from lawgraph.db.queries.instruments import (
    get_citing_judgments,
    get_instruments_list,
    most_cited_laws,
)
from lawgraph.db.queries.judgments import JudgmentFilters, get_judgments_list
from lawgraph.db.queries.nodes import get_node_with_neighbors
from lawgraph.db.queries.search import (
    load_code_aliases,
    load_notation_parser,
    search_all,
    tokenize_search_query,
)
from lawgraph.db.schema import SEARCH_FIELDS

logger = get_logger(__name__)


# The data version the last warm-up was done for (``/api/health`` says whether it is the
# current one).
_warmed: str | None = None


def warmed_version() -> str | None:
    """The data version the last warm-up was done for."""
    return _warmed


def is_warm(store: GraphStore) -> bool:
    """Whether the warm-up is done for the data as it is now."""
    return _warmed is not None and _warmed == store.data_version()


# The lists of decisions the explorer opens: of both Kamers and of the Tweede Kamer.
FIRST_DECISIONS = (DecisionFilters(), DecisionFilters(chamber="TK"))

# The newest cabinets, whose pages are warmed (each reads every paper its members signed).
WARM_CABINETS = 4


def _warm_cabinets(store: GraphStore) -> None:
    for item in get_cabinets(store)[:WARM_CABINETS]:
        get_cabinet(store, item["cabinet"]["_key"])


# The main areas of law with the most judgments, whose first page with facets is warmed
# (each counts the facets over every judgment of the area).
WARM_SUBJECT_AREAS = 5


# What the front end asks of a list first (its ``Bladeren``): the judgments of Rechtspraak,
# the instruments with articles and the papers of the Tweede Kamer. The facets and totals
# are kept per filter, so the warm-up asks with the same filters.
FIRST_JUDGMENTS = JudgmentFilters(source="rechtspraak")


def _warm_subject_areas(store: GraphStore) -> None:
    listed = get_judgments_list(store, FIRST_JUDGMENTS, limit=1)
    areas = (listed.get("facets") or {}).get("subject_area") or []
    for area in areas[:WARM_SUBJECT_AREAS]:
        if area.get("value"):
            get_judgments_list(
                store, replace(FIRST_JUDGMENTS, subject_area=area["value"]), limit=20
            )


# The laws with the most citations whose citing judgments are warmed: the first page as
# the front end asks it (its ``JUDGMENTS_SHOWN``, the newest first) with the years. The Awb
# and Sr are hundreds of thousands of judgments each.
WARM_LAWS = 15
LAW_JUDGMENTS_SHOWN = 100


def _warm_law_judgments(store: GraphStore) -> None:
    for bwb_id in most_cited_laws(store, WARM_LAWS):
        get_citing_judgments(store, bwb_id, limit=LAW_JUDGMENTS_SHOWN)


# The articles with the most citations whose node and citing passages are warmed: the node
# as it opens (its lid counts read every edge of it), and the passages as the front end asks
# them (the newest first, a page of 50; the most cited 6 for the homepage's network).
WARM_ARTICLES = 20
ARTICLE_PASSAGES = (("date_desc", 50), ("citation_count", 6))


def _warm_articles(store: GraphStore) -> None:
    for article in most_cited_articles(store, WARM_ARTICLES):
        get_node_with_neighbors(store, "articles", article["key"])
        for sort, limit in ARTICLE_PASSAGES:
            get_article_cited_by(store, article["id"], sort=sort, limit=limit)


# The tables a part of the warm-up reads, for the parts whose answers are kept per table
# (``version_cache.cached(tables=...)``): such a part is left out while its tables stand
# still, as a poll of judgments leaves the instruments. ``tests/pg/test_cached_tables.py``
# checks every one against the tables the plans of its statements read. A part not named
# here runs on every warm-up; one made of parts kept per table (``stats``) finds them kept.
PART_TABLES: dict[str, tuple[str, ...]] = {
    "coverage": (COLLECTION_JUDGMENTS,),
    "instruments": (
        COLLECTION_INSTRUMENTS,
        COLLECTION_INSTRUMENT_VERSIONS,
        COLLECTION_EDGES,
    ),
    "documents": (COLLECTION_DOCUMENTS,),
    "search notation": (COLLECTION_INSTRUMENTS,),
    "search codes": (COLLECTION_INSTRUMENTS,),
    "dossier law names": (COLLECTION_INSTRUMENTS,),
    "dossier names": (COLLECTION_DOSSIERS,),
    "member slugs": (COLLECTION_MEMBERS,),
    **{f"search {table}": (table,) for table in SEARCH_FIELDS},
}
# The version of its tables each of those parts was last warmed for, per database, in this
# process.
_warmed_parts: dict[tuple[str, str], str] = {}


def warm_up(store: GraphStore) -> None:
    """Compute what every visitor asks: each part on its own, so one that fails leaves the
    others, and one whose tables did not change since it was warmed left out; then the
    version it was done for is kept (``is_warm``)."""
    global _warmed
    version = store.data_version()
    parts: dict[str, Callable[[], object]] = {
        # cheap and asked most first, so that a deploy is warm for them within a minute
        "stats": lambda: stats_data(store),
        "coverage": lambda: coverage_data(store),
        "cabinets": lambda: _warm_cabinets(store),
        "instruments": lambda: get_instruments_list(
            store, article_count_min=1, limit=20
        ),
        "documents": lambda: list_documents(store, chambers=("TK",), limit=20),
        "search notation": lambda: load_notation_parser(store),
        "search codes": lambda: load_code_aliases(store),
        # the laws a dossier title names (``get_laws_named``)
        "dossier law names": lambda: load_law_names(store),
        "dossier names": lambda: load_dossier_names(store),
        "member slugs": lambda: load_member_slugs(store),
        **{
            f"search {table}": partial(search_statistics, store, table)
            for table in SEARCH_FIELDS
        },
        "judgments": lambda: get_judgments_list(store, FIRST_JUDGMENTS, limit=20),
        # the total and facets of the list of decisions as the explorer opens it, of both
        # Kamers and of the Tweede Kamer (``decision_counts``, kept per version of them)
        "decision counts": lambda: [
            decision_counts(store, filters) for filters in FIRST_DECISIONS
        ],
        # the slow ones last: the feed and every kind of it in one reading of the events
        # (``feed_counts``), then the largest areas of law
        "feed": lambda: get_feed(store, FeedFilters(), limit=50),
        "judgments by area of law": lambda: _warm_subject_areas(store),
        "judgments citing a law": lambda: _warm_law_judgments(store),
        "most cited articles": lambda: _warm_articles(store),
    }
    for name, part in parts.items():
        if version_cache.superseded(store, version):
            # newer data arrived: the warm-up of that version follows once it stands still
            logger.info("Warm-up stopped before %s: the data changed.", name)
            return
        tables = PART_TABLES.get(name)
        if tables is None:
            _run(name, part)
            continue
        stamp = store.data_version(tables)
        if _warmed_parts.get((store.name, name)) == stamp:
            logger.info(
                "Warm-up of %s left: %s did not change.", name, ", ".join(tables)
            )
        elif _run(name, part):
            _warmed_parts[(store.name, name)] = stamp
    _warmed = version
    logger.info("Warm-up done: %s.", ", ".join(parts))
    if _search_terms_due(store.name):
        _run("search terms", lambda: _warm_search_terms(store))


# The search of the terms searched most reads the pages of their index and hits into the
# memory of the database, where a warm-up of an hour ago left them also when a poll has
# written since, and keeps their document frequencies per data version (``_bm25``): a
# visitor after a poll gets those of the version before while the new ones compute. So it
# runs at most once per this many seconds per process.
SEARCH_TERMS_EVERY = 3600.0
# per database: when the warm-up last searched its terms (monotonic)
_terms_searched: dict[str, float] = {}


def _search_terms_due(database: str) -> bool:
    """Whether the warm-up of *database* searches the terms searched most now; it notes
    when it did."""
    now = time.monotonic()
    last = _terms_searched.get(database)
    if last is not None and now - last < SEARCH_TERMS_EVERY:
        logger.info(
            "Warm-up of search terms left: searched %s ago.",
            format_duration(now - last),
        )
        return False
    _terms_searched[database] = now
    return True


def forget() -> None:
    """Forget which parts were warmed and when the terms were searched (the tests)."""
    _warmed_parts.clear()
    _terms_searched.clear()


# The terms searched most in the last ``search_stats.KEEP_DAYS`` days whose search the warm-up
# runs, after everything else: their statistics, the pages of their index and of their
# hits read before the first visitor asks. Only a term asked ``search_stats.MIN_COUNT``
# times or more, as the counts keep them (one asked now and then may name a person).
WARM_SEARCH_TERMS = 5


def _warm_search_terms(store: GraphStore) -> None:
    counts = search_stats.totals(
        SEARCH_STATS_DIR, dt.date.today(), search_stats.KEEP_DAYS
    )
    terms = [term for term, n in counts.most_common() if n >= search_stats.MIN_COUNT]
    for term in terms[:WARM_SEARCH_TERMS]:
        if _common_word(store, term):
            continue
        search_all(store, q=term, types=sorted(SEARCH_TYPES), limit=20)


# A term whose judgments are more than this share of them is not searched by the warm-up:
# BM25 ranks every judgment that holds it (``_common_word``).
COMMON_SHARE = 0.10


def _common_word(store: GraphStore, term: str) -> bool:
    """Whether more than ``COMMON_SHARE`` of the judgments hold every word of *term*, by the
    planner's statistics of their summaries (``_bm25._common_elements``): its search would
    rank them all."""
    common = _bm25._common_elements(store, "judgments", "s_summary_t")
    rows = _bm25._estimated_rows(store, "judgments")
    words = tokenize_search_query(term)
    if not words or rows <= 0:
        return False
    # the judgments that hold every word: at most those of its least common word, a word
    # as common as its most common stem
    holding = min(
        max((common.get(stem, 0.0) for stem in _bm25._stems_of(store, w)), default=0.0)
        for w in words
    )
    return holding > COMMON_SHARE * rows


def _run(name: str, part: Callable[[], object]) -> bool:
    """One part of the warm-up, logged with how long it took; one that fails leaves the
    others. Whether it was done."""
    logger.info("Warm-up of %s.", name)
    began = time.monotonic()
    try:
        with version_cache.doing(f"warm-up: {name}"):
            part()
    except Exception as exc:  # noqa: BLE001 — the rest is still worth warming
        logger.warning("Warm-up of %s failed: %s: %s", name, type(exc).__name__, exc)
        return False
    logger.info(
        "Warm-up of %s took %s.", name, format_duration(time.monotonic() - began)
    )
    return True
