"""The search of a type by the words of its fields (``SEARCH_FIELDS``): ranked by BM25 over
the words a hit matches (``queries/_bm25.py``), each field weighed by its boost, or while
typing, nothing ranked; and the hits of a word searched often, kept ready to rank
(``candidates.py``)."""

from __future__ import annotations

import contextlib
import contextvars
import hashlib
import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from lawgraph.db import GraphStore
from lawgraph.db.queries._bm25 import bm25_inputs, bm25_sql
from lawgraph.db.queries.search.clause import Query, build_search_clause, live_clause
from lawgraph.db.queries.search.ranking import SCORE_IDENTIFIER
from lawgraph.db.queries.search.spec import Hit, SearchType
from lawgraph.db.request_context import Budget, read_budget, read_time_left
from lawgraph.db.schema import SEARCH_FIELDS, search_column, start_of_value_sql

# An article whose case law calls it by a word of the query (``lg_article_terms``) ranks as
# much higher as a word in its heading would (BM25 of a rare word, boosted).
TERM_WEIGHT = 10.0
# The most hits of a word that are ranked by it. Ranking reads the words of each hit (its
# search columns, kept apart from the row: half a millisecond a judgment from disk), so a
# common word ranked all of its hits ("belasting": 16,080 judgments, 8.5 s on prod); past
# this many hits only the first in the order of their columns are ranked
# (``SearchType.candidate_order``): the most cited, else the newest. Fewer hits are ranked
# whole.
RANK_CANDIDATES = 1000
# How much the case law that cites an article weighs in its rank: per e-fold of its citing
# judgments (``inbound_citation_count``), at most some 4 for the most cited (art. 6:162 BW,
# thousands). It settles hits whose words weigh about the same (a few points apart; a rank
# runs to some 30, a term ``TERM_WEIGHT``), and never lifts one past a better tier
# (``tier_sql``), which orders first.
CITATION_PRIOR = 0.5
# The rows a live search orders at most: a common word is in far more, and the first found
# stand for them (the full search after Enter ranks them all).
LIVE_CANDIDATES = 2_000


def tier_sql(named: bool, starts: str, titled: str) -> str:
    """SQL: the tier of a hit ``r`` among the hits of its type, which orders them before
    their rank, as ``score_hit`` orders them after it: 3 for an article the query names
    (*named*: its id in the parameter ``_named``, ``clause.Termed.named``), 2 for a hit
    whose name starts with the query (*starts*), 1 for one with every word in its name or
    a title it stands in (*titled*), else 0 (``SearchType.names`` and ``titles``). The
    database orders by it before the limit: a hit of a better tier is never left out for
    one its words and terms rank higher (art. 6:162 BW, in the title "Onrechtmatige daad",
    for the articles of the Wet conflictenrecht onrechtmatige daad, which its case law
    calls so too)."""
    parts = []
    if named:
        parts.append("WHEN r.id = ANY(%(_named)s::text[]) THEN 3")
    for condition, tier in ((starts, 2), (titled, 1)):
        if condition != "false":
            parts.append(f"WHEN {condition} THEN {tier}")
    return f"(CASE {' '.join(parts)} ELSE 0 END)" if parts else "0"


def titled_sql(kind: SearchType, words: list[str], row: str = "r") -> str:
    """SQL: every word (the parameters *words*) is a word of one of the fields of
    ``SearchType.titles`` of the row *row*, by its stems (``lg_tokens``) as the live
    search matches a word; ``false`` for a type without titles."""
    if not kind.titles:
        return "false"
    held = " OR ".join(
        f"{row}.{search_column(field, 'text')} @> lg_tokens(%({{word}})s)"
        for field in kind.titles
    )
    return " AND ".join(
        f"(cardinality(lg_tokens(%({word})s)) > 0 AND ({held.format(word=word)}))"
        for word in words
    )


def two_phase_search(
    store: GraphStore,
    precise: Query,
    text: Callable[[], Query],
    limit: int,
    precise_score: float | None = SCORE_IDENTIFIER,
    exact: bool = False,
    cited: bool = False,
) -> list[Hit]:
    """Run a precise lookup then a full-text fallback (the statement *text* makes),
    deduplicating by id.

    What the precise lookup finds is what the query names, so it scores as an identifier
    unless *precise_score* is None: then ``score_hit`` scores it like any hit. With *exact*
    it is the thing the query names (``ranking.exact_hit``). With *cited* the query is a
    citation (an article, an ECLI): what the lookup finds is all it asks, and the text is
    searched only when it finds nothing. The text has a budget of its own
    (``text_within_share``): past it, the precise hits are the answer.
    """
    seen: set[str] = set()
    results: list[Hit] = []
    for row in store.query(*precise):
        rid = row.get("id")
        if rid and rid not in seen:
            seen.add(rid)
            found = row if precise_score is None else {**row, "score": precise_score}
            results.append({**found, "exact": True} if exact else found)
    if len(results) < limit and not (cited and results):
        for row in text_within_share(store, text()):
            if row.get("id") not in seen:
                seen.add(row["id"])
                results.append(row)
    return results[:limit]


# The share of what a search has left that the text part of ``two_phase_search`` may read:
# the rest is for what comes after it (the persons a judgment names, its terms).
TEXT_SHARE = 0.8

# Whether a search of the context answered without the text part it ran out of time for
# (``answered_in_part``, ``text_within_share``).
_IN_PART: contextvars.ContextVar[Budget | None] = contextvars.ContextVar(
    "lawgraph_search_in_part", default=None
)


@contextlib.contextmanager
def answered_in_part() -> Iterator[Budget]:
    """Whether a search in the block answered its precise hits without its text part
    (``text_within_share``): ``ran_out``, a search cut off at its budget."""
    budget = Budget()
    token = _IN_PART.set(budget)
    try:
        yield budget
    finally:
        _IN_PART.reset(token)


def text_within_share(store: GraphStore, text: Query) -> list[Hit]:
    """The hits of the text search *text* within ``TEXT_SHARE`` of what the reads have
    left (all of it outside a request); none past it, the search answered in part
    (``answered_in_part``)."""
    left = read_time_left()
    if left is None:
        return list(store.query(*text, indexes_only=True))
    with read_budget(left * TEXT_SHARE, "The text part of a search"):
        return list(store.query(*text, indexes_only=True))
    in_part = _IN_PART.get()
    if in_part is not None:
        in_part.ran_out = True
    return []


def text_query(
    kind: SearchType,
    store: GraphStore,
    hit: str,
    tokens: list[str],
    limit: int,
    *,
    joins: str = "",
    where: str = "",
    params: dict[str, Any] | None = None,
    live: bool = False,
    termed: list[list[str]] | None = None,
    laws: list[list[str]] | None = None,
    named: set[str] | None = None,
    any_word: bool = False,
) -> Query:
    """The hits of *kind* that hold every token in its fields (with *any_word*: one at
    least, ranked by those they hold), the best ranked first (the key settles ties); *live*
    as ``live_query``. *termed*: per token the rows that have
    it as a term (``termed_articles``), found too and ranked ``TERM_WEIGHT`` higher, those
    it *named* in a tier above (``tier_sql``); *laws*:
    per token the laws whose articles it matches (``abbreviated_laws``). One word
    without a further condition ranks the hits kept of it (``kept_candidates``) while they
    are those of now: the same, without reading them.

    Run it with ``store.query(..., indexes_only=True)``: its conditions and its rank read
    the large search columns, whose detoasting the planner does not count, so for a
    common word it would scan the whole table instead of using the indexes."""
    if live:
        return live_query(
            kind,
            hit,
            tokens,
            limit,
            joins,
            where,
            params,
            termed,
            laws,
            named,
            any_word,
        )
    table = kind.table
    clause, clause_params = build_search_clause(
        table, tokens, kind.fields, termed=termed, laws=laws, any_word=any_word
    )
    words = {k: v for k, v in clause_params.items() if k.startswith("_tok_")}
    bm25 = bm25_sql(
        store, table, words, kind.fields, kind.boosts, kind.titles, kind.names
    )
    # a name that starts with the query: of one word, as its rank reads it (a hit kept of
    # the word has no columns but those of its rank); of more, from the columns of a name
    starts = (
        bm25.started
        if len(tokens) == 1
        else " OR ".join(
            start_of_value_sql(table, field, "%(_whole)s", "r") for field in kind.names
        )
        or "false"
    )
    # (not of the condition: the hits kept of a word are those of its condition alone)
    tier = tier_sql(bool(named), starts, bm25.titled)
    rank = bm25.rank
    if termed:
        bonus = " + ".join(
            f"(r.id = ANY(%(_termed_{i})s::text[]))::int" for i in range(len(tokens))
        )
        rank = f"({rank} + {TERM_WEIGHT} * ({bonus}))"
    if kind.citations:
        rank = f"({rank} + {CITATION_PRIOR} * ln(1 + coalesce({kind.citations}, 0)))"
    # Ranked on the search columns alone; only the hits kept are read for their props (a
    # judgment's props hold its whole text, and every read of a json prop parses them).
    # The matches are found first, on their own, from the indexes of the words (OFFSET 0
    # keeps the planner from walking the key index for them when every rank is the same,
    # or the index in the order of the candidates: that tests the words of row after row,
    # 60,000 judgments for "belasting"); of a common word only the ``RANK_CANDIDATES``
    # first in the order of their columns are ranked.
    candidates = (
        f"ORDER BY {kind.candidate_order} LIMIT {RANK_CANDIDATES}"
        if kind.candidate_order
        else ""
    )
    found = f"SELECT * FROM {table} r WHERE {clause} {where}"

    def ranked(found: str) -> str:
        return f"""
            SELECT r.id, {tier} AS tier, {rank} AS rank
            FROM (SELECT * FROM ({found} OFFSET 0) r {candidates}) r
            {bm25.lateral}
            ORDER BY tier DESC, rank DESC, r.key
            LIMIT %(limit)s
            """

    statement_params = {
        **clause_params,
        **bm25.params,
        **(params or {}),
        **({"_named": sorted(named)} if named else {}),
        "_whole": " ".join(tokens),
        "limit": limit,
    }
    kept = (
        None
        if where or len(tokens) != 1 or not kind.candidate_order
        else kept_candidates(store, kind, tokens[0], clause, clause_params)
    )
    if kept is None:
        top = ranked(found)
    else:
        # the hits kept of the word while they are those of now (``kept_candidates``), else
        # those found: the condition is the same for every row, so the one not taken is
        # not read (a one-time filter)
        gate, gate_params = kept
        statement_params.update(gate_params)
        top = f"""
            (SELECT r.id, {tier} AS tier, {rank} AS rank
             FROM (
                SELECT c.id, c.key, c.citations AS inbound_citation_count, c.tf, c.len
                FROM lg_search_candidates c
                WHERE c.collection = %(_kept_table)s AND c.word = %(_kept_word)s
                  AND {gate}
             ) r
             {bm25.stored}
             ORDER BY tier DESC, rank DESC, r.key
             LIMIT %(limit)s)
            UNION ALL
            ({ranked(f"{found} AND NOT {gate}")})
            """
    statement = f"""
        SELECT {hit}
        FROM ({top}) top
        JOIN {table} r ON r.id = top.id {joins}
        ORDER BY top.tier DESC, top.rank DESC, r.key
        """
    return statement, statement_params


# ── while typing ──────────────────────────────────────────────────────────────

# The query typed so far as the start of a folded value (``live_query``).
_LIVE_START = "lg_like(lg_fold(%(_live_q)s)) || '%%'"


def _first_found(table: str, condition: str) -> str:
    """SQL: the ids of the first ``LIVE_CANDIDATES`` rows of *table* that hold
    *condition*, one set of the candidates of a live search. They are found on their own,
    from the indexes of the words (OFFSET 0): within a ``UNION`` the planner would read
    them in the order of the ids, to merge the sets without a sort, walking the key index
    and testing every row (``burgerlijk wetboek`` in 732,000 articles)."""
    return (
        f"(SELECT f.id FROM (SELECT r.id FROM {table} r WHERE {condition} OFFSET 0) f"
        " LIMIT %(candidates)s)"
    )


def live_query(
    kind: SearchType,
    hit: str,
    tokens: list[str],
    limit: int,
    joins: str = "",
    where: str = "",
    params: dict[str, Any] | None = None,
    termed: list[list[str]] | None = None,
    laws: list[list[str]] | None = None,
    named: set[str] | None = None,
    any_word: bool = False,
) -> Query:
    """``text_query`` while typing: no word counted (the df of BM25) and none ranked.
    Every token (with *any_word*: one at least) is a word of the fields of *kind*, a whole value of one, or, from three
    characters, the start of a word of a name or title (``stik``: Stikstofwet); of the first
    ``LIVE_CANDIDATES`` found, in the tiers of ``score_hit``: those the query *named* (an
    article its case law calls so), those whose name or title starts with the query, those
    with every word in a name or a title they stand in (``SearchType.titles``), then those
    *termed*, then those first in its ``live_order``. The rows of a term and those of a
    title are candidates whatever the first found."""
    table = kind.table
    clause, clause_params = live_clause(
        table, tokens, kind.fields, termed, laws, any_word
    )
    starts = " OR ".join(
        f"r.{column} LIKE {_LIVE_START} OR r.{column} LIKE '%%' || chr(31) || {_LIVE_START}"
        for column in (
            search_column(f, "ngram")
            for f in kind.fields
            if "ngram" in SEARCH_FIELDS[table][f]
        )
    )
    titled = titled_sql(kind, [w for w in clause_params if w.startswith("_tok_")])
    order = [f"({starts or 'false'}) DESC"]
    found = [_first_found(table, f"{clause} {where}")]
    if titled != "false":
        order.append(f"({titled}) DESC")
        found.append(_first_found(table, f"{titled} AND {clause} {where}"))
    if termed:
        clause_params["_termed"] = sorted({row for rows in termed for row in rows})
        order.append("r.id = ANY(%(_termed)s::text[]) DESC")
        found.append(
            f"SELECT r.id FROM {table} r"
            f" WHERE r.id = ANY(%(_termed)s::text[]) AND {clause} {where}"
        )
    if named:
        clause_params["_named"] = sorted(named)
        order.insert(0, "r.id = ANY(%(_named)s::text[]) DESC")
    candidates = (
        f"SELECT r.* FROM ({' UNION '.join(found)}) found"
        f" JOIN {table} r ON r.id = found.id"
        if len(found) > 1
        else f"SELECT * FROM {table} r WHERE {clause} {where} LIMIT %(candidates)s"
    )
    order_by = ", ".join([*order, kind.live_order])
    # ordered on their ids and columns alone; only the hits kept are read for their props
    statement = f"""
        SELECT {hit}
        FROM (
            SELECT r.id, row_number() OVER (ORDER BY {order_by}) AS n
            FROM ({candidates}) r
            ORDER BY n
            LIMIT %(limit)s
        ) top
        JOIN {table} r ON r.id = top.id {joins}
        ORDER BY top.n
        """
    return statement, {
        **clause_params,
        **(params or {}),
        "_live_q": " ".join(tokens),
        "candidates": LIVE_CANDIDATES,
        "limit": limit,
    }


# ── the hits of a word searched often, kept ready ────────────────────────────

# Whether the hits kept of a word are those of now: read at the version of the type's table
# it is at (``lg_data_version``), for a search of the shape it has now.
_KEPT = """
    EXISTS (SELECT 1 FROM lg_search_candidates_state s
            JOIN lg_data_version v ON v.collection = s.collection AND v.version = s.version
            WHERE s.collection = %(_kept_table)s AND s.word = %(_kept_word)s
              AND s.signature = %(_kept_signature)s)
"""


@dataclass(frozen=True)
class CandidateSearch:
    """What the search of one word in a type reads of its hits: its condition and its
    parameters (``build_search_clause``), the SQL of what the rank reads of a hit
    (``_bm25.bm25_inputs``) and a signature of all of it."""

    clause: str
    params: dict[str, Any]
    tf: str
    lengths: str
    signature: str


def candidate_search(
    store: GraphStore, kind: SearchType, clause: str, clause_params: dict[str, Any]
) -> CandidateSearch:
    """The search of the one word of *clause* in *kind*. Its signature changes with
    whatever changes which hits it ranks or what it reads of them: the condition and its
    parameters (the forms of the word, the articles that have it as a term), the order of
    the candidates and their number, the terms and fields of the rank."""
    words = {k: v for k, v in clause_params.items() if k.startswith("_tok_")}
    tf, lengths, rank_params, shape = bm25_inputs(store, kind.table, words, kind.fields)
    signature = hashlib.sha256(
        json.dumps(
            [
                kind.table,
                clause,
                clause_params,
                kind.candidate_order,
                RANK_CANDIDATES,
                kind.citations,
                shape,
            ],
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return CandidateSearch(
        clause, {**clause_params, **rank_params}, tf, lengths, signature
    )


def kept_candidates(
    store: GraphStore,
    kind: SearchType,
    word: str,
    clause: str,
    clause_params: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """The condition that the hits kept of *word* in *kind* are those of now, and its
    parameters."""
    search = candidate_search(store, kind, clause, clause_params)
    return _KEPT, {
        "_kept_table": kind.table,
        "_kept_word": word,
        "_kept_signature": search.signature,
    }
