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
from lawgraph.config.settings import SEARCH_STATS_DIR
from lawgraph.core import search_stats
from lawgraph.core.logging import get_logger
from lawgraph.core.time import format_duration
from lawgraph.db import GraphStore, version_cache
from lawgraph.db.queries import _bm25
from lawgraph.db.queries._bm25 import _stats as search_statistics
from lawgraph.db.queries.cabinets import get_cabinet, get_cabinets
from lawgraph.db.queries.documents import list_documents
from lawgraph.db.queries.feed import FeedFilters, get_feed
from lawgraph.db.queries.instruments import get_instruments_list
from lawgraph.db.queries.judgments import JudgmentFilters, get_judgments_list
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


def warm_up(store: GraphStore) -> None:
    """Compute what every visitor asks: each part on its own, so one that fails leaves the
    others; then the version it was done for is kept (``is_warm``)."""
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
        **{
            f"search {table}": partial(search_statistics, store, table)
            for table in SEARCH_FIELDS
        },
        "judgments": lambda: get_judgments_list(store, FIRST_JUDGMENTS, limit=20),
        # the slow ones last: the feed and every kind of it in one reading of the events
        # (``feed_counts``), then the largest areas of law
        "feed": lambda: get_feed(store, FeedFilters(), limit=50),
        "judgments by area of law": lambda: _warm_subject_areas(store),
    }
    for name, part in parts.items():
        if version_cache.superseded(store, version):
            # newer data arrived: the warm-up of that version follows once it stands still
            logger.info("Warm-up stopped before %s: the data changed.", name)
            return
        _run(name, part)
    _warmed = version
    logger.info("Warm-up done: %s.", ", ".join(parts))
    _run("search terms", lambda: _warm_search_terms(store))


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


def _run(name: str, part: Callable[[], object]) -> None:
    """One part of the warm-up, logged with how long it took; one that fails leaves the
    others."""
    logger.info("Warm-up of %s.", name)
    began = time.monotonic()
    try:
        with version_cache.doing(f"warm-up: {name}"):
            part()
    except Exception as exc:  # noqa: BLE001 — the rest is still worth warming
        logger.warning("Warm-up of %s failed: %s: %s", name, type(exc).__name__, exc)
    else:
        logger.info(
            "Warm-up of %s took %s.", name, format_duration(time.monotonic() - began)
        )
