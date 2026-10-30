"""The search of several types at once (``search_all``), within a budget per type
(``search_full``) and while typing (``search_live``): each type of ``types.SEARCHES`` side by
side, its hits scored and ordered (``ranking.rank_hits``)."""

from __future__ import annotations

import functools
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from lawgraph.db import GraphStore
from lawgraph.db.queries._helpers import side_by_side
from lawgraph.db.queries.search.clause import (
    NO_PERIOD,
    Period,
    QueryWords,
    query_words,
)
from lawgraph.db.queries.search.counts import Counted, count_type
from lawgraph.db.queries.search.parser import kept_notation_parser, notation
from lawgraph.db.queries.search.ranking import rank_hits
from lawgraph.db.queries.search.signers import Signed, signed_for
from lawgraph.db.queries.search.spec import Asked, Hit
from lawgraph.db.queries.search.text import answered_in_part
from lawgraph.db.queries.search.types import SEARCHES
from lawgraph.db.store import read_budget
from lawgraph.db.version_cache import STALE_WAIT, stale_wait

Searches = dict[str, Callable[[], list[Hit]]]

# How long one type of the full search may rank (seconds): past it, the type answers what
# its live search finds within ``FALLBACK_BUDGET``, and is named in ``partial``, instead
# of the whole request answering 503 at its deadline. One deadline holds for them all, the
# two together (``full_deadline``): a type that waited for a thread of the pool has what is
# left of it, so the search ends within 2.5 s whatever the number of its types (a text
# search of a common word took 3.9 s).
FULL_BUDGET = 2.0
FALLBACK_BUDGET = 0.5
# How long the count of one type may take (seconds): past it the type has no count.
COUNT_BUDGET = 1.0
# How long one type of a live search may read (seconds): what it has not found by then, it
# answers empty and ``partial`` (the full search after Enter has it).
LIVE_BUDGET = 0.25
# What a search while typing waits for a kept answer of a new data version (the parser of
# citations reads every instrument: seconds after a poll) before it takes the one before.
LIVE_STALE_WAIT = 0.05

_SEARCHES = ThreadPoolExecutor(max_workers=4, thread_name_prefix="search")


def full_deadline() -> float:
    """When a full search started now must have answered (``time.monotonic``)."""
    return time.monotonic() + FULL_BUDGET + FALLBACK_BUDGET


def signed_of(
    store: GraphStore, q: str, types: list[str], words: QueryWords | None = None
) -> Signed | None:
    """The factions *q* names (``signers.signed_for``; of its *words*,
    ``clause.query_words``), when a type of *types* is kept to the hits signed for them:
    what a search of *q* filters on, and its answer says."""
    tokens = (words or query_words(store, q)).words
    if not tokens or not any(t in SEARCHES and SEARCHES[t].signatures for t in types):
        return None
    return signed_for(store, tokens)


def _asked(
    store: GraphStore,
    q: str,
    types: list[str],
    *,
    kinds: list[str] | None,
    limit: int,
    period: Period,
    signed: Signed | None,
    words: QueryWords | None,
    any_word: bool,
    motion_kinds: list[str] | None,
    wait: float = STALE_WAIT,
) -> Asked | None:
    """The search of *q* in *types*, of its *words* (``clause.query_words``); None when it
    has none, or when a citation is asked for by *any_word* (one of its parts is no word
    of what it cites). *wait*: how long the parser of citations is waited for."""
    words = words or query_words(store, q)
    if not words.words or (any_word and _cites(store, q, wait)):
        return None
    return Asked(
        store,
        q,
        words.words,
        notation(store, q, types, wait),
        kinds,
        limit,
        period,
        signed or signed_of(store, q, types, words),
        any_word,
        motion_kinds,
        words.order,
    )


def _cites(store: GraphStore, q: str, wait: float) -> bool:
    """Whether *q* is a citation (``core.notation``): an article, an ECLI, a Kamerstuk."""
    parser = kept_notation_parser(store, wait)
    return parser is not None and parser.parse(q) is not None


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
    signed: Signed | None = None,
    words: QueryWords | None = None,
    any_word: bool = False,
    motion_kinds: list[str] | None = None,
) -> dict[str, list[Hit]]:
    """Full-text search across requested entity types (of *period*: ``Period``).

    Returns a dict keyed by type name with a list of hit dicts each containing
    {id, key, collection, type, display_name, snippet, extra, score}, best score first.

    Every word of *q* but its stop words (*words*, ``clause.query_words``) must appear, or
    with *any_word* one of them at least: in the searched fields of the indexed types, in
    the names of members and factions; of the papers and the votes but those that name a
    faction (*signed*, ``signed_of``; found here without it), whose hits are signed for
    it; of these two only the motions of *motion_kinds* when it is given.
    """
    asked = _asked(
        store,
        q,
        types,
        kinds=kinds,
        limit=limit,
        period=period,
        signed=signed,
        words=words,
        any_word=any_word,
        motion_kinds=motion_kinds,
    )
    if asked is None:
        return {t: [] for t in types}
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
    signed: Signed | None = None,
    words: QueryWords | None = None,
    any_word: bool = False,
    motion_kinds: list[str] | None = None,
) -> tuple[dict[str, list[Hit]], set[str]]:
    """``search_all`` within ``FULL_BUDGET`` per type: a type that takes longer answers
    its live search (``search_live``: the judgments by name and display name, the most
    cited first, else the newest that hold the words; the other types by the start of a
    word of a name, without a rank).
    Returns the hits per type and the types that fell back."""
    hits, partial, _ = search_full_counted(
        store,
        q=q,
        types=types,
        kinds=kinds,
        limit=limit,
        period=period,
        signed=signed,
        words=words,
        any_word=any_word,
        motion_kinds=motion_kinds,
        counting=False,
    )
    return hits, partial


def search_full_counted(
    store: GraphStore,
    *,
    q: str,
    types: list[str],
    kinds: list[str] | None = None,
    limit: int = 20,
    period: Period = NO_PERIOD,
    signed: Signed | None = None,
    words: QueryWords | None = None,
    any_word: bool = False,
    motion_kinds: list[str] | None = None,
    counting: bool = True,
) -> tuple[dict[str, list[Hit]], set[str], dict[str, Counted | None]]:
    """``search_full`` and, with *counting*, how many hits each type has and how they
    divide (``counts.count_type``), side by side with the searches: per type that is
    counted (``SearchType.match``) its ``Counted``, None when it took longer than
    ``COUNT_BUDGET``; a type without a count is not in it."""
    asked = _asked(
        store,
        q,
        types,
        kinds=kinds,
        limit=limit,
        period=period,
        signed=signed,
        words=words,
        any_word=any_word,
        motion_kinds=motion_kinds,
    )
    if asked is None:
        return {t: [] for t in types}, set(), {}
    full = _searches(asked, types, live=False)
    live = _searches(asked, types, live=True)
    ends = full_deadline()
    tasks: dict[str, Callable[[], Any]] = {
        t: functools.partial(_full_or_live, full[t], live[t], ends) for t in full
    }
    counted = [t for t in full if counting and SEARCHES[t].match]
    tasks.update(
        {f"{t}{_COUNT}": functools.partial(_counted, t, asked) for t in counted}
    )
    found = _heavy_first(tasks)
    hits = {t: rank_hits(q, found[t][0]) for t in full}
    partial = {t for t in full if found[t][1]}
    return hits, partial, {t: found[f"{t}{_COUNT}"] for t in counted}


# The suffix of the task that counts a type, beside the one that searches it.
_COUNT = ":count"


def _counted(table: str, asked: Asked) -> Counted | None:
    """The count of the type *table* within ``COUNT_BUDGET``, None past it; none found
    for a type that has no date of its own when a period is asked."""
    kind = SEARCHES[table]
    if asked.period and not kind.period_date:
        return Counted(0, False, {facet.name: [] for facet in kind.facets})
    with read_budget(COUNT_BUDGET, "A count"):
        return count_type(kind, asked)
    return None


def _full_or_live(
    full: Callable[[], list[Hit]], live: Callable[[], list[Hit]], ends: float
) -> tuple[list[Hit], bool]:
    """The hits of *full* within ``FULL_BUDGET``, or what is left of the deadline *ends*
    (``time.monotonic``) less ``FALLBACK_BUDGET``; past it, its precise hits when it has
    them (``text.answered_in_part``), else those of *live* within ``FALLBACK_BUDGET``: cut
    off either way."""
    left = ends - FALLBACK_BUDGET - time.monotonic()
    rows, cut = _within_budget(full, max(0.0, min(FULL_BUDGET, left)))
    if not cut or rows:
        return rows, cut
    return _within_budget(live, FALLBACK_BUDGET)[0], True


def _heavy_first[R](searches: dict[str, Callable[[], R]]) -> dict[str, R]:
    """The result of each of *searches*, run side by side with the heavy types
    (``SearchType.heavy``, slowest first) handed to the pool first, the others one after
    another in the thread of the request meanwhile, so that the answer takes about as long
    as the slowest type; in the order of *searches*."""
    heavy = [t for t, kind in SEARCHES.items() if kind.heavy]

    def place(task: str) -> int:
        table = task.removesuffix(_COUNT)
        return heavy.index(table) if table in heavy else len(heavy)

    order = sorted(searches, key=place)
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
    signed: Signed | None = None,
    words: QueryWords | None = None,
    any_word: bool = False,
    motion_kinds: list[str] | None = None,
) -> tuple[dict[str, list[Hit]], set[str]]:
    """``search_all`` while typing: all types within ``LIVE_BUDGET``, nothing ranked by
    its words (``text.live_query``), and the judgments without their summaries: an ECLI,
    the name of a judgment, then the judgments whose display name (its court, date and case
    number) holds every word, the most cited first; when none does (a subject:
    ``onrechtmatige daad``), the newest that hold the words. Returns the hits per type and
    the types cut off at their budget."""
    with stale_wait(LIVE_STALE_WAIT):
        asked = _asked(
            store,
            q,
            types,
            kinds=kinds,
            limit=limit,
            period=period,
            signed=signed,
            words=words,
            any_word=any_word,
            motion_kinds=motion_kinds,
            wait=LIVE_STALE_WAIT,
        )
        if asked is None:
            return {t: [] for t in types}, set()
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
    the request has left); none and cut off when it takes longer, and cut off with its
    precise hits when its text part did (``text.answered_in_part``). A computation of the
    cache it waited for goes on."""
    with read_budget(LIVE_BUDGET if budget is None else budget, "A live search"):
        with answered_in_part() as in_part:
            hits = search()
        return hits, in_part.ran_out
    return [], True
