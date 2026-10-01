"""BM25 as ArangoSearch scored a search, for the order of its hits (D3).

ArangoSearch summed, over every term of the query a hit matches, BM25 of that term in that
field: ``boost × idf × tf × (k + 1) / (tf + k × (1 − b + b × len / avglen))`` with
``idf = ln(1 + (N − df + 0.5) / (df + 0.5))``, ``k`` 1.2 and ``b`` 0.75. The terms are those
of the four matches of ``queries/search.py``: each stem of a word (``text``), the word as
the start of a value (``identity``; a value is mostly unique, so its df is taken as 1), the
folded word as a whole value (``norm``) and the word as a part of the folded value
(``ngram``). The document frequencies of a query's terms are counted first, in one
statement of index lookups; the mean lengths of the fields per table once a minute.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from typing import Any

from lawgraph.core.cache import TTLCache
from lawgraph.db.schema import SEARCH_FIELDS, search_column

K1 = 1.2
B = 0.75

_stats_cache: TTLCache[str, dict[str, float]] = TTLCache(maxsize=16, ttl=60.0)
# The document frequencies of terms, per table, field, analyzer and term: they change with
# the data as the lengths do.
_df_cache: TTLCache[tuple[str, str, str, str], float] = TTLCache(maxsize=4096, ttl=60.0)
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
    """``N`` and the mean length per ``field/analyzer`` over the rows that have it."""
    with _stats_lock:
        cached = _stats_cache.get(table)
    if isinstance(cached, dict):
        return cached
    names = [
        f"{field}/{analyzer}"
        for field, analyzers in SEARCH_FIELDS[table].items()
        for analyzer in analyzers
    ]
    means = [
        f"avg(nullif({_length(*name.split('/'))}, 0))::float AS a{n}"
        for n, name in enumerate(names)
    ]
    row = next(
        store.query(f"SELECT count(*)::float AS n, {', '.join(means)} FROM {table} doc")
    )
    found = {"N": float(row["n"] or 0)}
    for n, name in enumerate(names):
        found[name] = float(row[f"a{n}"] or 1.0)
    with _stats_lock:
        _stats_cache.set(table, found)
    return found


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
    """The document frequency of each term, from the cache or counted in one statement."""
    keys = [(table, t.field, t.analyzer, str(params[t.param])) for t in terms]
    with _stats_lock:
        cached = [_df_cache.get(key) for key in keys]
    missing = [n for n, value in enumerate(cached) if not isinstance(value, float)]
    if missing:
        counts = [f"{_df(table, terms[n])} AS d{n}" for n in missing]
        # Counted from the indexes: a scan would detoast the search columns of every row.
        row = next(
            store.query(f"SELECT {', '.join(counts)}", params, indexes_only=True)
        )
        with _stats_lock:
            for n in missing:
                counted = float(row[f"d{n}"])
                cached[n] = counted
                _df_cache.set(keys[n], counted)
    return [float(value) for value in cached]  # type: ignore[arg-type]


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
