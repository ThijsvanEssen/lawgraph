"""The search of several types at once (``search_all``), within a budget per type
(``search_full``) and while typing (``search_live``): each type of ``types.SEARCHES`` side by
side, its hits scored and ordered (``ranking.rank_hits``)."""

from __future__ import annotations

import functools
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from lawgraph.db import GraphStore
from lawgraph.db.queries._helpers import side_by_side
from lawgraph.db.queries.search.clause import NO_PERIOD, Period, tokenize_search_query
from lawgraph.db.queries.search.parser import notation
from lawgraph.db.queries.search.ranking import rank_hits
from lawgraph.db.queries.search.spec import Asked, Hit
from lawgraph.db.queries.search.types import SEARCHES
from lawgraph.db.store import read_budget
from lawgraph.db.version_cache import stale_wait

Searches = dict[str, Callable[[], list[Hit]]]

# How long one type of the full search may rank (seconds): past it, the type answers what
# its live search finds within ``FALLBACK_BUDGET``, and is named in ``partial``, instead
# of the whole request answering 503 at its deadline.
FULL_BUDGET = 3.0
FALLBACK_BUDGET = 1.0
# How long one type of a live search may read (seconds): what it has not found by then, it
# answers empty and ``partial`` (the full search after Enter has it).
LIVE_BUDGET = 0.25
# What a search while typing waits for a kept answer of a new data version (the parser of
# citations reads every instrument: seconds after a poll) before it takes the one before.
LIVE_STALE_WAIT = 0.05

_SEARCHES = ThreadPoolExecutor(max_workers=4, thread_name_prefix="search")


def _searches(asked: Asked, types: list[str], live: bool) -> Searches:
    """The search of each of *types* that is one (*live*: while typing, nothing ranked by
    its words); with a period a type without a date of its own finds nothing."""
    return {
        t: (
            functools.partial(SEARCHES[t].search, SEARCHES[t], asked, live)
            if not asked.period or SEARCHES[t].period_date
            else list
        )
        for t in types
        if t in SEARCHES
    }


def search_all(
    store: GraphStore,
    *,
    q: str,
    types: list[str],
    kinds: list[str] | None = None,
    limit: int = 20,
    period: Period = NO_PERIOD,
) -> dict[str, list[Hit]]:
    """Full-text search across requested entity types (of *period*: ``Period``).

    Returns a dict keyed by type name with a list of hit dicts each containing
    {id, key, collection, type, display_name, snippet, extra, score}, best score first.

    Every token must appear — AND semantics: in the searched fields of the indexed types,
    in the names of members and factions.
    """
    tokens = tokenize_search_query(q)
    if not tokens:
        return {t: [] for t in types}
    asked = Asked(store, q, tokens, notation(store, q, types), kinds, limit, period)
    found = _heavy_first(_searches(asked, types, live=False))
    return {t: rank_hits(q, hits) for t, hits in found.items()}


def search_full(
    store: GraphStore,
    *,
    q: str,
    types: list[str],
    kinds: list[str] | None = None,
    limit: int = 20,
    period: Period = NO_PERIOD,
) -> tuple[dict[str, list[Hit]], set[str]]:
    """``search_all`` within ``FULL_BUDGET`` per type: a type that takes longer answers
    its live search (``search_live``: the judgments by name and display name, the most
    cited first, else the newest that hold the words; the other types by the start of a
    word of a name, without a rank).
    Returns the hits per type and the types that fell back."""
    tokens = tokenize_search_query(q)
    if not tokens:
        return {t: [] for t in types}, set()
    asked = Asked(store, q, tokens, notation(store, q, types), kinds, limit, period)
    full = _searches(asked, types, live=False)
    live = _searches(asked, types, live=True)
    found = _heavy_first(
        {t: functools.partial(_full_or_live, full[t], live[t]) for t in full}
    )
    hits = {t: rank_hits(q, rows) for t, (rows, _) in found.items()}
    partial = {t for t, (_, cut) in found.items() if cut}
    return hits, partial


def _full_or_live(
    full: Callable[[], list[Hit]], live: Callable[[], list[Hit]]
) -> tuple[list[Hit], bool]:
    """The hits of *full* within ``FULL_BUDGET``; past it, those of *live* within
    ``FALLBACK_BUDGET``, cut off."""
    rows, cut = _within_budget(full, FULL_BUDGET)
    if not cut:
        return rows, False
    return _within_budget(live, FALLBACK_BUDGET)[0], True


def _heavy_first[R](searches: dict[str, Callable[[], R]]) -> dict[str, R]:
    """The result of each of *searches*, run side by side with the heavy types
    (``SearchType.heavy``, slowest first) handed to the pool first, the others one after
    another in the thread of the request meanwhile, so that the answer takes about as long
    as the slowest type; in the order of *searches*."""
    heavy = [t for t, kind in SEARCHES.items() if kind.heavy]
    order = sorted(searches, key=lambda t: heavy.index(t) if t in heavy else len(heavy))
    found = dict(
        zip(order, side_by_side(_SEARCHES, [searches[t] for t in order]), strict=True)
    )
    return {t: found[t] for t in searches}


def search_live(
    store: GraphStore,
    *,
    q: str,
    types: list[str],
    kinds: list[str] | None = None,
    limit: int = 10,
    period: Period = NO_PERIOD,
) -> tuple[dict[str, list[Hit]], set[str]]:
    """``search_all`` while typing: all types within ``LIVE_BUDGET``, nothing ranked by
    its words (``text.live_query``), and the judgments without their summaries: an ECLI,
    the name of a judgment, then the judgments whose display name (its court, date and case
    number) holds every word, the most cited first; when none does (a subject:
    ``onrechtmatige daad``), the newest that hold the words. Returns the hits per type and
    the types cut off at their budget."""
    tokens = tokenize_search_query(q)
    if not tokens:
        return {t: [] for t in types}, set()
    with stale_wait(LIVE_STALE_WAIT):
        asked = Asked(
            store,
            q,
            tokens,
            notation(store, q, types, LIVE_STALE_WAIT),
            kinds,
            limit,
            period,
        )
        searches = _searches(asked, types, live=True)
        # one budget for them all: a type that waited for a thread (``side_by_side`` runs
        # those for which none is free one after another) has what is left of it
        ends = time.monotonic() + LIVE_BUDGET
        found = side_by_side(
            _SEARCHES,
            [
                functools.partial(_within_live_budget, search, ends)
                for search in searches.values()
            ],
        )
    hits = {t: rank_hits(q, rows) for t, (rows, _) in zip(searches, found, strict=True)}
    partial = {t for t, (_, cut) in zip(searches, found, strict=True) if cut}
    return hits, partial


def _within_live_budget(
    search: Callable[[], list[Hit]], ends: float
) -> tuple[list[Hit], bool]:
    """``_within_budget`` with what is left until *ends* (``time.monotonic``)."""
    return _within_budget(search, max(0.0, ends - time.monotonic()))


def _within_budget(
    search: Callable[[], list[Hit]], budget: float | None = None
) -> tuple[list[Hit], bool]:
    """The hits of *search* within *budget* seconds (``LIVE_BUDGET`` without one; or what
    the request has left); none and cut off when it takes longer. A computation of the
    cache it waited for goes on."""
    with read_budget(LIVE_BUDGET if budget is None else budget, "A live search"):
        return search(), False
    return [], True
