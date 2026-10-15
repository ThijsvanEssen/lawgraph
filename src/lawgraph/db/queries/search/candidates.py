"""The hits of the words searched most, ready to rank (``schema.SEARCH_CANDIDATES``).

A search of one word in the judgments, articles or documents ranks the first
``RANK_CANDIDATES`` of its hits in the order of their columns (``text.text_query``). Of a
common word it reads every hit to find those (16,080 judgments for "belasting", 18,000 pages
from disk when they are not in memory), then the large columns of each it ranks. Here that
is done once per word and type: its hits in that order, with what the rank reads of each.
A search takes them while they are those of now (``text.kept_candidates``: read at the
version of the type's table it is at, for a search of the shape it has now) and finds them
itself otherwise, to the same hits in the same order.

The words are the one-word terms of ``/api/search`` asked at least ``search_stats.MIN_COUNT``
times in the last ``search_stats.KEEP_DAYS`` days (``core/search_stats.py``), the
``WORDS`` asked most: those whose cold search is felt, and none that may name a person.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

from lawgraph.core import search_stats
from lawgraph.db import GraphStore
from lawgraph.db.queries.search.clause import (
    abbreviated_laws,
    build_search_clause,
    termed_articles,
    tokenize_search_query,
)
from lawgraph.db.queries.search.spec import SearchType
from lawgraph.db.queries.search.text import (
    RANK_CANDIDATES,
    CandidateSearch,
    candidate_search,
)
from lawgraph.db.queries.search.types import SEARCHES

# The most words whose hits are kept: each is read again after every write to its tables.
WORDS = 50
# The types whose hits of a word are kept: those of which a common word ranks only its first
# ``RANK_CANDIDATES`` hits.
CANDIDATE_TYPES = [kind for kind in SEARCHES.values() if kind.candidate_order]


@dataclass(frozen=True)
class Written:
    """What a run kept: per type the words read again, and those left as they were."""

    written: dict[str, dict[str, int]]
    current: dict[str, int]
    dropped: int


def searched_words(directory: Path, today: dt.date, most: int = WORDS) -> list[str]:
    """The one-word terms asked at least ``MIN_COUNT`` times in the last ``KEEP_DAYS``
    days, the *most* asked most (ties by the word)."""
    counts = search_stats.totals(directory, today, search_stats.KEEP_DAYS)
    words: dict[str, int] = {}
    for term, n in counts.items():
        tokens = tokenize_search_query(term)
        if n >= search_stats.MIN_COUNT and len(tokens) == 1:
            words[tokens[0]] = words.get(tokens[0], 0) + n
    return sorted(words, key=lambda w: (-words[w], w))[:most]


def _search(store: GraphStore, kind: SearchType, word: str) -> CandidateSearch:
    """The search of *word* in *kind*, as ``text.text_query`` makes it."""
    articles = kind.table == "articles"
    clause, clause_params = build_search_clause(
        kind.table,
        [word],
        kind.fields,
        termed=termed_articles(store, [word]) if articles else None,
        laws=abbreviated_laws(store, [word]) if articles else None,
    )
    return candidate_search(store, kind, clause, clause_params)


def write_word(store: GraphStore, kind: SearchType, word: str) -> int:
    """Read the hits of *word* in *kind* again; how many it has."""
    search = _search(store, kind, word)
    table, order = kind.table, kind.candidate_order
    citations = kind.citations or "NULL::double precision"
    # its hits in the order the search ranks them from, with what their rank reads of each;
    # the version of the table they were read at in the same statement (one snapshot)
    statement = f"""
        WITH hits AS (
            SELECT doc.id, doc.key, {citations} AS citations, {search.tf} AS tf,
                   {search.lengths} AS len, doc.n, doc.total
            FROM (
                SELECT doc.*, row_number() OVER (ORDER BY {order}) AS n,
                       count(*) OVER () AS total
                FROM (SELECT * FROM {table} doc WHERE {search.clause} OFFSET 0) doc
                ORDER BY {order}
                LIMIT {RANK_CANDIDATES}
            ) doc
        ),
        kept AS (
            INSERT INTO lg_search_candidates
                (collection, word, pos, id, key, citations, tf, len)
            SELECT %(_kept_table)s, %(_kept_word)s, n, id, key, citations, tf, len
            FROM hits
            ON CONFLICT (collection, word, pos) DO UPDATE
            SET id = EXCLUDED.id, key = EXCLUDED.key, citations = EXCLUDED.citations,
                tf = EXCLUDED.tf, len = EXCLUDED.len
        ),
        gone AS (
            DELETE FROM lg_search_candidates
            WHERE collection = %(_kept_table)s AND word = %(_kept_word)s
              AND pos > (SELECT count(*) FROM hits)
        ),
        state AS (
            INSERT INTO lg_search_candidates_state
                (collection, word, version, signature, hits)
            SELECT %(_kept_table)s, %(_kept_word)s, v.version, %(_kept_signature)s,
                   coalesce((SELECT max(total) FROM hits), 0)
            FROM lg_data_version v WHERE v.collection = %(_kept_table)s
            ON CONFLICT (collection, word) DO UPDATE
            SET version = EXCLUDED.version, signature = EXCLUDED.signature,
                hits = EXCLUDED.hits
            RETURNING hits
        )
        SELECT hits FROM state
        """
    params = {
        **search.params,
        "_kept_table": table,
        "_kept_word": word,
        "_kept_signature": search.signature,
    }
    with store.pool.connection() as conn, conn.transaction():
        # found from the indexes of the word, as the search finds them: the planner prices
        # the detoasting of the words of every row at nothing (``GraphStore.query``)
        conn.execute("SET LOCAL enable_seqscan = off")
        row = conn.execute(statement.encode(), params).fetchone()
    return int(row[0]) if row else 0


def _current(store: GraphStore, table: str) -> dict[str, str]:
    """Per word of *table* whose hits were read at the version of its table of now: the
    signature of the search they were read for."""
    rows = store.query(
        """
        SELECT s.word, s.signature FROM lg_search_candidates_state s
        JOIN lg_data_version v ON v.collection = s.collection AND v.version = s.version
        WHERE s.collection = %(table)s
        """,
        {"table": table},
    )
    return {row["word"]: row["signature"] for row in rows}


def write(store: GraphStore, words: list[str], every: bool = False) -> Written:
    """Keep the hits of *words* in every type: a word again where its table changed since
    it was read, or the search it was read for (*every*: all of them); the words no longer
    asked go."""
    written: dict[str, dict[str, int]] = {}
    current: dict[str, int] = {}
    for kind in CANDIDATE_TYPES:
        table = kind.table
        kept = {} if every else _current(store, table)
        written[table] = {}
        current[table] = 0
        for word in words:
            if word in kept and kept[word] == _search(store, kind, word).signature:
                current[table] += 1
                continue
            written[table][word] = write_word(store, kind, word)
    dropped = store.execute(
        """
        WITH gone AS (
            DELETE FROM lg_search_candidates WHERE NOT word = ANY(%(words)s::text[])
        )
        DELETE FROM lg_search_candidates_state WHERE NOT word = ANY(%(words)s::text[])
        RETURNING word
        """,
        {"words": words},
    )
    return Written(written, current, len(dropped))
