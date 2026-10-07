"""The answers every visitor asks first, computed before they ask: at the start of the API
and whenever the data version changes (``version_cache.on_new_version``), in the background.
The facets and totals of the unfiltered lists, the statistics and coverage, the
statistics of the search and the pages of the newest cabinets. Off with
``LAWGRAPH_API_WARM_UP=false``."""

from __future__ import annotations

import time
from collections.abc import Callable
from functools import partial

from lawgraph.api.routes.stats import coverage_data, stats_data
from lawgraph.core.logging import get_logger
from lawgraph.core.time import format_duration
from lawgraph.db import GraphStore, version_cache
from lawgraph.db.queries._bm25 import _stats as search_statistics
from lawgraph.db.queries.cabinets import get_cabinet, get_cabinets
from lawgraph.db.queries.documents import list_documents
from lawgraph.db.queries.feed import FEED_KINDS, FeedFilters, get_feed
from lawgraph.db.queries.instruments import get_instruments_list
from lawgraph.db.queries.judgments import JudgmentFilters, get_judgments_list
from lawgraph.db.queries.search import load_code_aliases, load_notation_parser
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


def warm_up(store: GraphStore) -> None:
    """Compute what every visitor asks: each part on its own, so one that fails leaves the
    others; then the version it was done for is kept (``is_warm``)."""
    global _warmed
    version = store.data_version()
    parts: dict[str, Callable[[], object]] = {
        # what the first visitors ask first: the lists and the search
        "judgments": lambda: get_judgments_list(store, JudgmentFilters(), limit=20),
        "search notation": lambda: load_notation_parser(store),
        "search codes": lambda: load_code_aliases(store),
        **{
            f"search {table}": partial(search_statistics, store, table)
            for table in SEARCH_FIELDS
        },
        "feed": lambda: get_feed(store, FeedFilters(), limit=50),
        "instruments": lambda: get_instruments_list(store, limit=20),
        "documents": lambda: list_documents(store, limit=20),
        "stats": lambda: stats_data(store),
        "coverage": lambda: coverage_data(store),
        **{
            f"feed {kind}": partial(
                get_feed, store, FeedFilters(kinds=(kind,)), limit=50
            )
            for kind in FEED_KINDS
        },
        "cabinets": lambda: _warm_cabinets(store),
    }
    for name, part in parts.items():
        if version_cache.superseded(store, version):
            # newer data arrived: the warm-up of that version follows once it stands still
            logger.info("Warm-up stopped before %s: the data changed.", name)
            return
        logger.info("Warm-up of %s.", name)
        began = time.monotonic()
        try:
            part()
        except Exception as exc:  # noqa: BLE001 — the rest is still worth warming
            logger.warning(
                "Warm-up of %s failed: %s: %s", name, type(exc).__name__, exc
            )
        else:
            logger.info(
                "Warm-up of %s took %s.",
                name,
                format_duration(time.monotonic() - began),
            )
    _warmed = version
    logger.info("Warm-up done: %s.", ", ".join(parts))
