"""The search of a type by the words of its fields (``SEARCH_FIELDS``): ranked by BM25 over
the words a hit matches (``queries/_bm25.py``), each field weighed by its boost, or while
typing, nothing ranked; and the hits of a word searched often, kept ready to rank
(``candidates.py``)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from lawgraph.db import GraphStore
from lawgraph.db.queries._bm25 import bm25_inputs, bm25_sql
from lawgraph.db.queries.search.clause import Query, build_search_clause, live_clause
from lawgraph.db.queries.search.ranking import SCORE_IDENTIFIER
from lawgraph.db.queries.search.spec import Hit, SearchType
from lawgraph.db.schema import SEARCH_FIELDS, search_column

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
# (``score_hit``), which orders first.
CITATION_PRIOR = 0.5
# The rows a live search orders at most: a common word is in far more, and the first found
# stand for them (the full search after Enter ranks them all).
LIVE_CANDIDATES = 2_000


def two_phase_search(
    store: GraphStore,
    precise: Query,
    text: Query,
    limit: int,
    precise_score: float | None = SCORE_IDENTIFIER,
) -> list[Hit]:
    """Run a precise lookup then a full-text fallback, deduplicating by id.

    What the precise lookup finds is what the query names, so it scores as an identifier
    unless *precise_score* is None: then ``score_hit`` scores it like any hit.
    """
    seen: set[str] = set()
    results: list[Hit] = []
    for row in store.query(*precise):
        rid = row.get("id")
        if rid and rid not in seen:
            seen.add(rid)
            results.append(
                row if precise_score is None else {**row, "score": precise_score}
            )
    if len(results) < limit:
        for row in store.query(*text, indexes_only=True):
            if row.get("id") not in seen:
                seen.add(row["id"])
                results.append(row)
    return results[:limit]


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
) -> Query:
    """The hits of *kind* that hold every token in its fields, the best ranked first (the
    key settles ties); *live* as ``live_query``. *termed*: per token the rows that have
    it as a term (``termed_articles``), found too and ranked ``TERM_WEIGHT`` higher; *laws*:
    per token the laws whose articles it matches (``abbreviated_laws``). One word
    without a further condition ranks the hits kept of it (``kept_candidates``) while they
    are those of now: the same, without reading them.

    Run it with ``store.query(..., indexes_only=True)``: its conditions and its rank read
    the large search columns, whose detoasting the planner does not count, so for a
    common word it would scan the whole table instead of using the indexes."""
    if live:
        return live_query(kind, hit, tokens, limit, joins, where, params, termed, laws)
    table = kind.table
    clause, clause_params = build_search_clause(
        table, tokens, kind.fields, termed=termed, laws=laws
    )
    words = {k: v for k, v in clause_params.items() if k.startswith("_tok_")}
    bm25 = bm25_sql(store, table, words, kind.fields, kind.boosts)
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
            SELECT r.id, {rank} AS rank
            FROM (SELECT * FROM ({found} OFFSET 0) r {candidates}) r
            {bm25.lateral}
            ORDER BY rank DESC, r.key
            LIMIT %(limit)s
            """

    statement_params = {
        **clause_params,
        **bm25.params,
        **(params or {}),
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
            (SELECT r.id, {rank} AS rank
             FROM (
                SELECT c.id, c.key, c.citations AS inbound_citation_count, c.tf, c.len
                FROM lg_search_candidates c
                WHERE c.collection = %(_kept_table)s AND c.word = %(_kept_word)s
                  AND {gate}
             ) r
             {bm25.stored}
             ORDER BY rank DESC, r.key
             LIMIT %(limit)s)
            UNION ALL
            ({ranked(f"{found} AND NOT {gate}")})
            """
    statement = f"""
        SELECT {hit}
        FROM ({top}) top
        JOIN {table} r ON r.id = top.id {joins}
        ORDER BY top.rank DESC, r.key
        """
    return statement, statement_params


# ── while typing ──────────────────────────────────────────────────────────────

# The query typed so far as the start of a folded value (``live_query``).
_LIVE_START = "lg_like(lg_fold(%(_live_q)s)) || '%%'"


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
) -> Query:
    """``text_query`` while typing: no word counted (the df of BM25) and none ranked.
    Every token is a word of the fields of *kind*, a whole value of one, or, from three
    characters, the start of a word of a name or title (``stik``: Stikstofwet); of the first
    ``LIVE_CANDIDATES`` found, those whose name or title starts with the query first (as
    ``score_hit``), then those first in its ``live_order``."""
    table = kind.table
    clause, clause_params = live_clause(table, tokens, kind.fields, termed, laws)
    starts = " OR ".join(
        f"r.{column} LIKE {_LIVE_START} OR r.{column} LIKE '%%' || chr(31) || {_LIVE_START}"
        for column in (
            search_column(f, "ngram")
            for f in kind.fields
            if "ngram" in SEARCH_FIELDS[table][f]
        )
    )
    order = f"({starts or 'false'}) DESC, {kind.live_order}"
    candidates = f"SELECT * FROM {table} r WHERE {clause} {where} LIMIT %(candidates)s"
    if termed:
        # the rows that have a token as a term are candidates whatever the first found,
        # by their keys, and come after those whose name starts with the query
        clause_params["_termed"] = sorted({row for rows in termed for row in rows})
        order = (
            f"({starts or 'false'}) DESC, r.id = ANY(%(_termed)s::text[]) DESC, "
            + (kind.live_order)
        )
        candidates = (
            f"SELECT r.* FROM ("
            f"(SELECT r.id FROM {table} r WHERE {clause} {where}"
            f" LIMIT %(candidates)s) UNION"
            f" SELECT r.id FROM {table} r"
            f" WHERE r.id = ANY(%(_termed)s::text[]) AND {clause} {where}"
            f") found JOIN {table} r ON r.id = found.id"
        )
    # ordered on their ids and columns alone; only the hits kept are read for their props
    statement = f"""
        SELECT {hit}
        FROM (
            SELECT r.id, row_number() OVER (ORDER BY {order}) AS n
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
