"""The answers every visitor asks first, computed before they ask: at the start of the API
and whenever the data version changes (``version_cache.on_new_version``), in the background.
The facets and totals of the unfiltered lists, the statistics and coverage, the heat, and
the statistics of the search. Off with ``LAWGRAPH_API_WARM_UP=false``."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial

from lawgraph.api.routes.nodes import heat_counts
from lawgraph.api.routes.stats import coverage_data, stats_data
from lawgraph.core.logging import get_logger
from lawgraph.db import GraphStore
from lawgraph.db.queries._bm25 import _stats as search_statistics
from lawgraph.db.queries.documents import list_documents
from lawgraph.db.queries.feed import FEED_KINDS, FeedFilters, get_feed
from lawgraph.db.queries.instruments import get_instruments_list
from lawgraph.db.queries.judgments import JudgmentFilters, get_judgments_list
from lawgraph.db.schema import SEARCH_FIELDS

logger = get_logger(__name__)


def warm_up(store: GraphStore) -> None:
    """Compute what every visitor asks: each part on its own, so one that fails leaves the
    others."""
    parts: dict[str, Callable[[], object]] = {
        "stats": lambda: stats_data(store),
        "coverage": lambda: coverage_data(store),
        "judgments": lambda: get_judgments_list(store, JudgmentFilters(), limit=20),
        "instruments": lambda: get_instruments_list(store, limit=20),
        "documents": lambda: list_documents(store, limit=20),
        "heat": lambda: heat_counts(store),
        "feed": lambda: get_feed(store, FeedFilters(), limit=50),
        **{
            f"feed {kind}": partial(
                get_feed, store, FeedFilters(kinds=(kind,)), limit=50
            )
            for kind in FEED_KINDS
        },
        **{
            f"search {table}": partial(search_statistics, store, table)
            for table in SEARCH_FIELDS
        },
    }
    for name, part in parts.items():
        try:
            part()
        except Exception as exc:  # noqa: BLE001 — the rest is still worth warming
            logger.warning(
                "Warm-up of %s failed: %s: %s", name, type(exc).__name__, exc
            )
    logger.info("Warm-up done: %s.", ", ".join(parts))
