"""BM25 as ArangoSearch scored a search, for the order of its hits (D3).

ArangoSearch summed, over every term of the query a hit matches, BM25 of that term in that
field: ``boost × idf × tf × (k + 1) / (tf + k × (1 − b + b × len / avglen))`` with
``idf = ln(1 + (N − df + 0.5) / (df + 0.5))``, ``k`` 1.2 and ``b`` 0.75. The terms are those
of the four matches of ``queries/search.py``: each stem of a word (``text``), the word as
the start of a value (``identity``; a value is mostly unique, so its df is taken as 1), the
folded word as a whole value (``norm``) and the word as a part of the folded value
(``ngram``). The document frequencies of a query's terms are counted first, in one
statement of index lookups; the mean lengths of the fields per table once per data version,
from a sample on a large table.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from typing import Any

from lawgraph.core.logging import get_logger
from lawgraph.core.word_forms import word_forms
from lawgraph.db.schema import SEARCH_FIELDS, search_column, start_of_value_sql
from lawgraph.db.store import (
    ReadTimedOut,
    read_time_left,
    reset_read_deadline,
    set_read_deadline,
)
from lawgraph.db.version_cache import lasting, stale_wait

logger = get_logger(__name__)

K1 = 1.2
B = 0.75
# The rows a large table's mean field lengths are taken from (``_stats``).
SAMPLE_ROWS = 20_000
# A field found fewer times in the sample is measured over the whole table (``_stats``).
MIN_SAMPLED = 100
# How long the statistics of a table are kept (seconds), whatever the data does.
STATS_MAX_AGE = 6 * 3600.0
# How long the counts of the document frequencies of one search of a table may take
# together (seconds): every term and field in one statement, under this one deadline or
# what the search has left, whichever ends first (``_counted``).
DF_TIMEOUT = 5.0

# The statistics of a table and the document frequencies of terms are kept per data version
# (``version_cache``): on the full graph they take a minute, and change only with the data.
# The stems of a word: what the stemmer makes of it does not change.
_stems: dict[str, list[str]] = {}
# The types of one search are scored side by side; the caches are not thread-safe.
_stats_lock = threading.Lock()


@dataclass(frozen=True)
class _Term:
    """One term of the query in one field under one analyzer."""

    field: str
    analyzer: str
    param: str  # the parameter that holds the term (a stem, or the word)
    boost: float


def _length(field: str, analyzer: str) -> str:
    """The length of *field* of ``doc`` under *analyzer*: its tokens, values or ngrams."""
    column = f"doc.{search_column(field, analyzer)}"
    if analyzer == "ngram":
        return f"lg_ngrams(char_length({column}))"
    return f"coalesce(cardinality({column}), 0)"


def _stats(store: Any, table: str) -> dict[str, float]:
    """``N`` and the mean length per ``field/analyzer`` over the rows that have it. On a
    large table these are estimates: ``N`` is the planner's count (``pg_class.reltuples``)
    and the means are those of a sample of ``SAMPLE_ROWS`` rows, the same pages every time,
    as counting a million judgments takes minutes from disk. A field the sample holds
    fewer than ``MIN_SAMPLED`` times (the names of a judgment: a few hundred of a million)
    is measured over the whole table, reading that field alone (a scan of the table, not of
    its large values). Kept ``STATS_MAX_AGE`` whatever the data does, computed on the
    background connections: a run of the pipelines hardly moves them."""

    def count() -> dict[str, float]:
        names = [
            f"{field}/{analyzer}"
            for field, analyzers in SEARCH_FIELDS[table].items()
            for analyzer in analyzers
        ]
        estimate = _estimated_rows(store, table)
        if estimate < SAMPLE_ROWS * 5:
            n, means, _ = _means(store, table, names, "")
            return {"N": n, **means}
        percent = 100.0 * SAMPLE_ROWS / estimate
        _, means, seen = _means(
            store, table, names, f" TABLESAMPLE SYSTEM ({percent:.6f}) REPEATABLE (0)"
        )
        rare = [name for name in names if seen[name] < MIN_SAMPLED]
        if rare:
            means.update(_means(store, table, rare, "")[1])
        return {"N": estimate, **means}

    return lasting(store, ("bm25-stats", table), count, STATS_MAX_AGE)


def _means(
    store: Any, table: str, names: list[str], sample: str
) -> tuple[float, dict[str, float], dict[str, int]]:
    """The rows of *table* (or of its *sample*), and per name the mean length over the rows
    that have the field (1 when none has it) and how many have it."""
    lengths = [_length(*name.split("/")) for name in names]
    columns = [
        f"avg(nullif({length}, 0))::float AS a{n}, count(nullif({length}, 0)) AS c{n}"
        for n, length in enumerate(lengths)
    ]
    row = next(
        store.query(
            f"SELECT count(*)::float AS n, {', '.join(columns)} FROM {table} doc"
            + sample
        )
    )
    means = {name: float(row[f"a{n}"] or 1.0) for n, name in enumerate(names)}
    seen = {name: int(row[f"c{n}"]) for n, name in enumerate(names)}
    return float(row["n"] or 0), means, seen


def _stats_now(store: Any, table: str) -> dict[str, float]:
    """``_stats`` of *table* without waiting, in a request: the kept answer, an earlier one
    while a newer is computed, or, when none is kept yet (after a start, before the warm-up
    computed it, behind the slow computations of the pool), an estimate: ``N`` as the planner
    counts the rows and no mean lengths, so the rank weighs no length (``bm25_sql``) until
    the statistics are kept. Outside a request (the warm-up, a pipeline) it waits for them."""
    if read_time_left() is None:
        return _stats(store, table)
    token = set_read_deadline(0.0)
    try:
        with stale_wait(0.0):
            return _stats(store, table)
    except ReadTimedOut:
        pass  # computed on, for the next search
    finally:
        reset_read_deadline(token)
    return {"N": max(_estimated_rows(store, table), 1.0)}


def _estimated_rows(store: Any, table: str) -> float:
    """The rows of *table* as the planner counts them (-1 before its first ``ANALYZE``)."""
    return float(
        next(
            store.query(
                "SELECT reltuples::float FROM pg_class WHERE oid = %(table)s::regclass",
                {"table": table},
            )
        )
    )


def _tf(term: _Term) -> str:
    """How often the term occurs in the field of ``doc``."""
    column = f"doc.{search_column(term.field, term.analyzer)}"
    p = f"%({term.param})s"
    if term.analyzer == "text":
        return f"cardinality(array_positions({column}, {p}::text))"
    if term.analyzer == "identity":
        # from three characters, as the condition of the search matches a start of a value
        return (
            f"(CASE WHEN char_length({p}) >= 3 THEN (SELECT count(*) FROM unnest({column})"
            f" AS v WHERE starts_with(lg_fold(v), lg_fold({p}))) ELSE 0 END)"
        )
    if term.analyzer == "norm":
        return f"cardinality(array_positions({column}, lg_fold({p})))"
    return (
        f"(CASE WHEN char_length({p}) BETWEEN 3 AND 12 THEN"
        f" (char_length({column}) - char_length(replace({column}, lg_fold({p}), '')))"
        f" / char_length({p}) ELSE 0 END)"
    )


def _df(table: str, term: _Term) -> str:
    """How many rows of *table* hold the term in the field (one index lookup)."""
    column = search_column(term.field, term.analyzer)
    p = f"%({term.param})s"
    if term.analyzer == "text":
        return f"(SELECT count(*) FROM {table} WHERE {column} && ARRAY[{p}]::text[])"
    if term.analyzer == "norm":
        return f"(SELECT count(*) FROM {table} WHERE {column} && ARRAY[lg_fold({p})])"
    if term.analyzer == "ngram":
        return (
            f"(SELECT count(*) FROM {table} WHERE char_length({p}) BETWEEN 3 AND 12"
            f" AND {column} LIKE '%%' || replace(replace(replace(lg_fold({p}),"
            f" '\\', '\\\\'), '%%', '\\%%'), '_', '\\_') || '%%')"
        )
    # identity: the rows that have a value starting with the word, of three characters or
    # more (as the condition of the search, ``search._field_condition``)
    start = start_of_value_sql(table, term.field, p, row="")
    return f"(SELECT count(*) FROM {table} WHERE char_length({p}) >= 3 AND {start})"


def _stems_of(store: Any, word: str) -> list[str]:
    with _stats_lock:
        known = _stems.get(word)
    if known is None:
        known = list(next(store.query("SELECT lg_tokens(%(w)s)", {"w": word})))
        with _stats_lock:
            if len(_stems) > 100_000:
                _stems.clear()
            _stems[word] = known
    return known


def _frequencies(
    store: Any, table: str, terms: list[_Term], params: dict[str, Any], rows: float
) -> list[float]:
    """The document frequency of each term. A word whose stem is one of the most common
    elements of its column (``_common_elements``) takes the frequency the planner keeps of
    it; every other term is counted, in one statement, and kept ``STATS_MAX_AGE`` whatever
    the data does, as the statistics of the table are: a poll hardly moves how many rows
    hold a word, and counting a common one reads thousands of rows from disk (articles
    "belasting": 3.6 s on prod). A request never waits for a count it does not have: it
    takes the estimate of ``_estimated_frequencies`` and the count is made in the
    background, for the next search. Outside a request (the warm-up) it waits."""
    if not terms:
        return []
    key = (
        "bm25-df",
        table,
        tuple((t.field, t.analyzer, str(params[t.param])) for t in terms),
    )

    common = {
        column: _common_elements(store, table, column)
        for column in {
            search_column(t.field, t.analyzer) for t in terms if t.analyzer == "text"
        }
    }

    def count() -> list[float]:
        found: dict[int, float] = {}
        for n, term in enumerate(terms):
            if term.analyzer == "text":
                known = common[search_column(term.field, term.analyzer)]
                if str(params[term.param]) in known:
                    found[n] = known[str(params[term.param])]
        counted = [n for n in range(len(terms)) if n not in found]
        if counted:
            found.update(_counted(store, table, terms, params, counted, rows))
        return [found[n] for n in range(len(terms))]

    if read_time_left() is None:
        return lasting(store, key, count, STATS_MAX_AGE)
    token = set_read_deadline(0.0)
    try:
        with stale_wait(0.0):
            return lasting(store, key, count, STATS_MAX_AGE)
    except ReadTimedOut:
        pass  # counted on, for the next search
    finally:
        reset_read_deadline(token)
    return _estimated_frequencies(terms, params, common, rows)


def _estimated_frequencies(
    terms: list[_Term],
    params: dict[str, Any],
    common: dict[str, dict[str, float]],
    rows: float,
) -> list[float]:
    """The frequency of each term without counting, while the count is made: of a stem among
    the most common elements of its column the planner's; of another word, half the least
    common of those, as the planner itself estimates an element it keeps no frequency of
    (it is rarer than every one it keeps); of a term of another analyzer (a prefix, a part
    of a value), one in a thousand rows."""
    estimates = []
    for term in terms:
        if term.analyzer != "text":
            estimates.append(max(rows / 1000.0, 1.0))
            continue
        known = common.get(search_column(term.field, term.analyzer)) or {}
        word = str(params[term.param])
        if word in known:
            estimates.append(known[word])
        else:
            estimates.append(max(min(known.values(), default=rows / 1000.0) / 2.0, 1.0))
    return estimates


def _counted(
    store: Any,
    table: str,
    terms: list[_Term],
    params: dict[str, Any],
    counted: list[int],
    rows: float,
) -> dict[int, float]:
    """The document frequencies of the terms *counted*, in one statement of index lookups,
    within ``DF_TIMEOUT`` seconds. A count that takes longer is of terms too common to tell
    apart: each takes *rows*, so it weighs next to nothing in the rank and still keeps the
    rows that hold it (a short part of a word that half the rows start with). One cut off
    by the end of the search instead is no frequency: ``ReadTimedOut``, and nothing kept."""
    counts = [f"{_df(table, terms[n])} AS d{n}" for n in counted]
    # Counted from the indexes: a scan would detoast the search columns of every row.
    # (one more column: a row of one column is its value, not a dict)
    statement = f"SELECT 1 AS one, {', '.join(counts)}"
    left = read_time_left()
    if left is not None and left < DF_TIMEOUT:
        # the search ends first: its ReadTimedOut goes up, and nothing is kept
        row = next(store.query(statement, params, indexes_only=True))
        return {n: float(row[f"d{n}"]) for n in counted}
    token = set_read_deadline(DF_TIMEOUT)
    try:
        row = next(store.query(statement, params, indexes_only=True))
    except ReadTimedOut:
        logger.info(
            "The frequencies of a search of %s took over %s s: taken as every row.",
            table,
            DF_TIMEOUT,
        )
        return dict.fromkeys(counted, rows)
    finally:
        reset_read_deadline(token)
    return {n: float(row[f"d{n}"]) for n in counted}


def _common_elements(store: Any, table: str, column: str) -> dict[str, float]:
    """The most common elements of the array *column* of *table* and the rows that hold
    each, as ``ANALYZE`` sampled them (``pg_stats``: its share of the rows times the rows of
    the table), kept ``STATS_MAX_AGE``; empty before the table is analyzed."""

    def read() -> dict[str, float]:
        row = next(
            store.query(
                """
                SELECT coalesce(s.most_common_elems::text::text[], '{}') AS elements,
                       coalesce(s.most_common_elem_freqs, '{}') AS shares,
                       (SELECT reltuples::float FROM pg_class
                        WHERE oid = %(table)s::regclass) AS n
                FROM (SELECT 1) one
                LEFT JOIN pg_stats s ON s.schemaname = current_schema()
                    AND s.tablename = %(table)s AND s.attname = %(column)s
                """,
                {"table": table, "column": column},
            )
        )
        rows = max(float(row["n"] or 0), 0.0)
        # the shares end with three of their own (the least, the most, of null elements)
        return {
            element: share * rows
            for element, share in zip(row["elements"], row["shares"], strict=False)
        }

    # read by the search itself (``inline``): one row of ``pg_stats``
    return lasting(
        store, ("bm25-common", table, column), read, STATS_MAX_AGE, inline=True
    )


def _terms(
    store: Any,
    table: str,
    words: dict[str, str],
    fields: list[str],
    boosts: dict[str, float],
) -> tuple[list[_Term], dict[str, Any]]:
    params: dict[str, Any] = dict(words)
    # the stems of a word and of its forms that stem apart, as the search matches it
    stems = {word: _stems_of(store, word_forms(value)) for word, value in words.items()}
    terms = []
    for word in words:
        for field in fields:
            for analyzer in SEARCH_FIELDS[table][field]:
                boost = boosts.get(field, 1.0)
                if analyzer != "text":
                    terms.append(_Term(field, analyzer, word, boost))
                    continue
                for stem in stems[word]:
                    param = f"_stem_{len(params)}"
                    params[param] = stem
                    terms.append(_Term(field, analyzer, param, boost))
    return terms, params


def bm25_sql(
    store: Any,
    table: str,
    words: dict[str, str],
    fields: list[str],
    boosts: dict[str, float],
) -> tuple[str, str, dict[str, Any]]:
    """The BM25 of a row ``doc`` of *table* for the words (parameter name → word) in
    *fields*: ``(rank, lateral, params)``. *lateral* (``CROSS JOIN LATERAL …``, to follow
    ``FROM {table} doc``) reads the frequency and length of each term once per row; *rank*
    adds them up."""
    terms, params = _terms(store, table, words, fields, boosts)
    if not terms:
        return "0", "", params
    stats = _stats_now(store, table)
    frequencies = _frequencies(store, table, terms, params, stats["N"])
    columns, parts = [], []
    lengths: dict[tuple[str, str], str] = {}  # one length per field and analyzer
    for n, term in enumerate(terms):
        df = frequencies[n]
        if df == 0:
            continue  # a term no row holds adds nothing to any rank
        if term.analyzer == "identity":
            df = 1.0  # a value is mostly its own term
        weight = term.boost * math.log(1 + (stats["N"] - df + 0.5) / (df + 0.5))
        avglen = stats.get(f"{term.field}/{term.analyzer}")
        # without its mean length (an estimate, ``_stats_now``) no length is weighed: b = 0
        b = B if avglen else 0.0
        length = lengths.get((term.field, term.analyzer))
        if length is None:
            length = lengths[(term.field, term.analyzer)] = f"l{len(lengths)}"
            columns.append(f"{_length(term.field, term.analyzer)} AS {length}")
        columns.append(f"{_tf(term)} AS t{n}")
        parts.append(
            f"CASE WHEN f.t{n} > 0 THEN {weight * (K1 + 1)} * f.t{n}"
            f" / (f.t{n} + {K1 * (1 - b)} + {K1 * b / (avglen or 1.0)} * f.{length}) ELSE 0 END"
        )
    if not parts:
        return "0", "", params
    lateral = f"CROSS JOIN LATERAL (SELECT {', '.join(columns)} OFFSET 0) f"
    return "(" + " + ".join(parts) + ")", lateral, params
