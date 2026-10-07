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

from lawgraph.db.schema import SEARCH_FIELDS, search_column
from lawgraph.db.version_cache import cached, lasting

K1 = 1.2
B = 0.75
# The rows a large table's mean field lengths are taken from (``_stats``).
SAMPLE_ROWS = 20_000
# A field found fewer times in the sample is measured over the whole table (``_stats``).
MIN_SAMPLED = 100
# How long the statistics of a table are kept (seconds), whatever the data does.
STATS_MAX_AGE = 6 * 3600.0

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
        return f"(SELECT count(*) FROM unnest({column}) AS v WHERE starts_with(v, {p}))"
    if term.analyzer == "norm":
        return f"cardinality(array_positions({column}, lg_fold({p})))"
    return (
        f"(CASE WHEN char_length({p}) BETWEEN 3 AND 12 THEN"
        f" (char_length({column}) - char_length(replace({column}, {p}, '')))"
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
            f" AND {column} LIKE '%%' || replace(replace(replace({p}, '\\', '\\\\'),"
            f" '%%', '\\%%'), '_', '\\_') || '%%')"
        )
    # identity: the rows that have a value starting with the word
    return (
        f"(SELECT count(*) FROM {table} WHERE"
        f" {search_column(term.field, 'prefix')} LIKE '%%' || chr(31) || lg_like({p}) || '%%')"
    )


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
    store: Any, table: str, terms: list[_Term], params: dict[str, Any]
) -> list[float]:
    """The document frequency of each term, kept per data version. A word whose stem is one
    of the most common elements of its column (``_common_elements``) takes the frequency the
    planner keeps of it; every other term is counted, in one statement: for a common word
    those counts were the slowest part of a search (2 s of 3 on the full graph)."""
    if not terms:
        return []
    key = (
        "bm25-df",
        table,
        tuple((t.field, t.analyzer, str(params[t.param])) for t in terms),
    )

    # read here, not in the computation below: a computation of the cache does not wait
    # for another one (they share a pool, whose workers would all wait for each other)
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
            counts = [f"{_df(table, terms[n])} AS d{n}" for n in counted]
            # Counted from the indexes: a scan would detoast the search columns of every
            # row. (one more column: a row of one column is its value, not a dict)
            row = next(
                store.query(
                    f"SELECT 1 AS one, {', '.join(counts)}", params, indexes_only=True
                )
            )
            found.update({n: float(row[f"d{n}"]) for n in counted})
        return [found[n] for n in range(len(terms))]

    return cached(store, key, count)


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

    return lasting(store, ("bm25-common", table, column), read, STATS_MAX_AGE)


def _terms(
    store: Any,
    table: str,
    words: dict[str, str],
    fields: list[str],
    boosts: dict[str, float],
) -> tuple[list[_Term], dict[str, Any]]:
    params: dict[str, Any] = dict(words)
    stems = {word: _stems_of(store, value) for word, value in words.items()}
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
    stats = _stats(store, table)
    frequencies = _frequencies(store, table, terms, params)
    columns, parts = [], []
    lengths: dict[tuple[str, str], str] = {}  # one length per field and analyzer
    for n, term in enumerate(terms):
        df = frequencies[n]
        if df == 0:
            continue  # a term no row holds adds nothing to any rank
        if term.analyzer == "identity":
            df = 1.0  # a value is mostly its own term
        weight = term.boost * math.log(1 + (stats["N"] - df + 0.5) / (df + 0.5))
        avglen = stats[f"{term.field}/{term.analyzer}"]
        length = lengths.get((term.field, term.analyzer))
        if length is None:
            length = lengths[(term.field, term.analyzer)] = f"l{len(lengths)}"
            columns.append(f"{_length(term.field, term.analyzer)} AS {length}")
        columns.append(f"{_tf(term)} AS t{n}")
        parts.append(
            f"CASE WHEN f.t{n} > 0 THEN {weight * (K1 + 1)} * f.t{n}"
            f" / (f.t{n} + {K1 * (1 - B)} + {K1 * B / avglen} * f.{length}) ELSE 0 END"
        )
    if not parts:
        return "0", "", params
    lateral = f"CROSS JOIN LATERAL (SELECT {', '.join(columns)} OFFSET 0) f"
    return "(" + " + ".join(parts) + ")", lateral, params
