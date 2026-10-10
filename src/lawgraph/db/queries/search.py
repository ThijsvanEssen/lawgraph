"""Full-text and structured search query helpers.

A word of the query matches a field as ArangoSearch matched it (probed, PR #102): by its
stemmed tokens (``text``), as the start of a value in any case (``identity``), as the whole
folded value (``norm``) or as a part of 3 to 12 characters of the folded value (``ngram``).
Every word must match some field. Which fields have which matches is ``SEARCH_FIELDS`` of
``db/schema.py``; the columns are generated there. The rank within a type is ``ts_rank``
over the weighted words (``search_tsv``), not ArangoSearch's BM25: the hits are the same,
their order is held to D3.
"""

from __future__ import annotations

import datetime as dt
import functools
import re
import time
import unicodedata
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from lawgraph.config.constants import COLLECTION_INSTRUMENTS
from lawgraph.core.aliases import code_aliases, curated_abbreviations
from lawgraph.core.dossier_numbers import short_title
from lawgraph.core.logging import get_logger
from lawgraph.core.models import make_node_key
from lawgraph.core.notation import Notation, NotationParser
from lawgraph.core.word_forms import word_forms
from lawgraph.db import GraphStore
from lawgraph.db.queries._bm25 import bm25_sql
from lawgraph.db.queries._helpers import chamber_sql, side_by_side
from lawgraph.db.queries.semantic.bwb import code_alias_rows
from lawgraph.db.schema import (
    INSTRUMENT_DATE_IN_FORCE,
    SEARCH_FIELDS,
    search_column,
    search_words,
    start_of_value_sql,
)
from lawgraph.db.store import (
    ReadTimedOut,
    read_time_left,
    reset_read_deadline,
    set_read_deadline,
)
from lawgraph.db.version_cache import STALE_WAIT, cached, stale_wait

logger = get_logger(__name__)

# The score of a hit is the tier of the best way it matches the query. Ties keep the order
# of the database (the rank within a type).
SCORE_IDENTIFIER = 1.0  # the query is the hit's key or one of its identifiers
SCORE_TITLE = 0.75  # the query is the whole of its name
SCORE_PREFIX = 0.5  # its name starts with the query
SCORE_CONTAINS = 0.25  # every word of the query is in its name
SCORE_WORDS = 0.1  # it matched on stems or text only

# The weights of ``search_tsv`` (D, C, B, A): the boosts of the fields, 1, 1.5, 2 and 4.
_RANK_WEIGHTS = "{0.25, 0.375, 0.5, 1.0}"

Query = tuple[str, dict[str, Any]]


def _not_null(*values: str) -> str:
    """``NOT_NULL(a, b, …)`` of JSON values: the first that is neither missing nor null."""
    cases = " ".join(
        f"WHEN coalesce(json_typeof({v}), 'null') <> 'null' THEN {v}" for v in values
    )
    return f"(CASE {cases} END)"


# ── a period ──────────────────────────────────────────────────────────────────

# The date of a hit a period (``from``, ``to``) asks for, of a row ``{row}``: of each type its
# own (a judgment the day of its decision, a paper its date, a dossier the day it was opened,
# a vote its date, a commitment the day it was made, a law the day it came into force, as
# the index ``instruments_date_in_force`` reads it), and of an article that of its law. A
# type not named has no date of its own: with a period it finds nothing.
PERIOD_DATES: dict[str, str] = {
    "judgments": "{row}.date_eff",
    "documents": "{row}.date",
    "dossiers": "{row}.opened_on",
    "decisions": "{row}.date",
    "commitments": "{row}.made_on",
    "instruments": INSTRUMENT_DATE_IN_FORCE.replace("props", "{row}.props"),
    "articles": (
        "(SELECT "
        + INSTRUMENT_DATE_IN_FORCE.replace("props", "i.props")
        + " FROM instruments i WHERE i.bwb_id = {row}.bwb_id ORDER BY i.key LIMIT 1)"
    ),
}


@dataclass(frozen=True)
class Period:
    """The days a search keeps its hits to: from *start* to *end*, both included
    (YYYY-MM-DD); either open."""

    start: str | None = None
    end: str | None = None

    def __bool__(self) -> bool:
        return bool(self.start or self.end)

    def where(self, table: str, row: str = "doc") -> str:
        """``AND`` the date of a row of *table* in the period (empty without one); a date
        with a time of the last day is in it (before the day after)."""
        if not self:
            return ""
        column = PERIOD_DATES[table].format(row=row)
        parts = []
        if self.start:
            parts.append(f"{column} >= %(_period_from)s")
        if self.end:
            parts.append(f"{column} < %(_period_until)s")
        return " AND " + " AND ".join(parts)

    def params(self) -> dict[str, Any]:
        found: dict[str, Any] = {}
        if self.start:
            found["_period_from"] = self.start
        if self.end:
            day = dt.date.fromisoformat(self.end) + dt.timedelta(days=1)
            found["_period_until"] = day.isoformat()
        return found

    def keeps(self, table: str) -> bool:
        """Whether a hit of *table* can be in the period: every type without one, only
        those with a date of their own with one."""
        return not self or table in PERIOD_DATES


NO_PERIOD = Period()


# ── the condition of a search ─────────────────────────────────────────────────


def _field_condition(table: str, field: str, word: str, row: str) -> list[str]:
    """How *field* of *table* (the row *row*) matches the word in the parameter *word*,
    one condition per analyzer it was indexed with."""
    analyzers = SEARCH_FIELDS[table][field]
    parts = []
    if "text" in analyzers:
        # its forms that stem apart too ("huurprijs" and "huurprijzen": ``word_forms``)
        forms = word.replace("_tok_", "_forms_")
        parts.append(f"{row}.{search_column(field, 'text')} && lg_tokens(%({forms})s)")
    # Each of them an index lookup: GIN on the arrays, trigrams on the strings.
    if "identity" in analyzers:
        # from three characters, as a part of a value: the start of a value of two (``hu``,
        # ``st``) is that of a large share of the rows, which the trigrams cannot narrow;
        # in any case, and without accents where the field is folded (``start_of_value_sql``)
        start = start_of_value_sql(table, field, f"%({word})s", row)
        parts.append(f"(char_length(%({word})s) >= 3 AND {start})")
    if "norm" in analyzers:
        parts.append(
            f"{row}.{search_column(field, 'norm')} @> ARRAY[lg_fold(%({word})s)]"
        )
    if "ngram" in analyzers:
        parts.append(
            f"(char_length(%({word})s) BETWEEN 3 AND 12"
            f" AND {row}.{search_column(field, 'ngram')}"
            f" LIKE '%%' || lg_like(lg_fold(%({word})s)) || '%%')"
        )
    return parts


def build_search_clause(
    table: str,
    tokens: list[str],
    fields: list[str],
    row: str = "doc",
    termed: list[list[str]] | None = None,
) -> tuple[str, dict[str, Any]]:
    """A condition on *row* (a row of *table*): every token matches one of *fields*.

    Returns ``(condition, params)``; the parameters are ``_tok_0``, ``_tok_1``, … so they
    do not collide with those of the caller. A token is taken as typed (lower case, from
    ``tokenize_search_query``): its stems for the words of a field, as is for a prefix of
    its value or a part of it, folded for a whole folded value. ``_forms_0``, … hold the
    forms of each that stem apart (``word_forms``). *termed* holds per token the rows
    that have it as a term (``_termed``: an article by what its case law calls it), each
    found by its key as well.
    """
    if not tokens:
        return "true", {}
    params: dict[str, Any] = {}
    parts: list[str] = []
    for i, token in enumerate(tokens):
        word = f"_tok_{i}"
        params[word] = token
        params[f"_forms_{i}"] = word_forms(token)
        per_field = [c for f in fields for c in _field_condition(table, f, word, row)]
        if termed:
            params[f"_termed_{i}"] = termed[i]
            per_field.append(f"{row}.id = ANY(%(_termed_{i})s::text[])")
        parts.append("(" + " OR ".join(per_field) + ")")
    return " AND ".join(parts), params


def rank_sql(tokens: list[str]) -> Query:
    """The rank of ``doc`` for *tokens*: how much of its weighted words are their stems."""
    return (
        f"ts_rank('{_RANK_WEIGHTS}', doc.search_tsv, ("
        "SELECT coalesce(string_agg(quote_literal(t), ' | ')::tsquery, ''::tsquery)"
        " FROM unnest(lg_tokens_all(%(_rank_words)s::text[])) AS t), 1)",
        {"_rank_words": tokens},
    )


def tokenize_search_query(q: str) -> list[str]:
    """Split a free-text query into lowercase tokens for AND-matching.

    Whitespace is the only separator; punctuation is preserved inside tokens
    so identifiers like ``BWBR0001903`` or ``ECLI:NL:HR:2023:1`` remain intact.
    Tokens of length 1 are dropped to avoid pathological scans.
    """
    return [t for t in q.strip().lower().split() if len(t) > 1]


# ── Intent-aware search parser ────────────────────────────────────────────────


def load_code_aliases(store: GraphStore) -> dict[str, str]:
    """Law abbreviation (``Sr``, ``AVG``) → BWB id or CELEX number
    (``core.aliases.code_aliases``), kept per data version."""
    return cached(
        store,
        ("code-aliases",),
        lambda: code_aliases(code_alias_rows(store), curated_abbreviations()),
        tables=(COLLECTION_INSTRUMENTS,),
    )


def _load_law_names(store: GraphStore) -> dict[str, list[str]]:
    """Lower-case law name → the BWB or CELEX ids that carry it (a name may be shared); the
    ids of one name are listed in one order every time."""
    rows = store.query(
        """
        SELECT coalesce(bwb_id, celex) AS law_id,
               json_build_array(
                   props -> 'short_title', props -> 'citation_title', props -> 'title'
               ) AS names
        FROM instruments
        WHERE coalesce(bwb_id, celex) IS NOT NULL
        ORDER BY law_id, key
        """
    )
    names: dict[str, list[str]] = {}
    for row in rows:
        for name in row["names"]:
            if isinstance(name, str) and name.strip():
                known = names.setdefault(name.strip().lower(), [])
                if row["law_id"] not in known:
                    known.append(row["law_id"])
    return names


def load_notation_parser(store: GraphStore) -> NotationParser:
    """The parser of typed citations over the laws in the graph, kept per data version:
    it reads every instrument (134,000 on the full graph), once for every search and
    resolve until the data changes, and once while many ask (``version_cache``)."""
    return cached(
        store,
        ("notation-parser",),
        # the aliases computed here, not through ``load_code_aliases``: a computation of
        # the cache does not wait for another one (they share a pool)
        lambda: NotationParser(
            code_aliases(code_alias_rows(store), curated_abbreviations()),
            _load_law_names(store),
        ),
        tables=(COLLECTION_INSTRUMENTS,),
    )


def kept_notation_parser(store: GraphStore, wait: float) -> NotationParser | None:
    """The parser of citations, waited for *wait* seconds at most (or what the request has
    left): None when none is kept yet and it is not computed by then (after a start, before
    the warm-up computed it, behind the slow computations of the pool). A search then goes
    on without it, the query taken as words, instead of waiting."""
    left = read_time_left()
    token = set_read_deadline(wait if left is None else min(wait, left))
    try:
        return load_notation_parser(store)
    except ReadTimedOut:
        logger.info("No parser of citations within %s s: searched as words.", wait)
        return None
    finally:
        reset_read_deadline(token)


# ── Per-type search helpers ───────────────────────────────────────────────────


def _two_phase_search(
    store: GraphStore,
    precise: Query,
    text: Query,
    limit: int,
    precise_score: float | None = SCORE_IDENTIFIER,
) -> list[dict[str, Any]]:
    """Run a precise lookup then a full-text fallback, deduplicating by id.

    What the precise lookup finds is what the query names, so it scores as an identifier
    unless *precise_score* is None: then ``score_hit`` scores it like any hit.
    """
    seen: set[str] = set()
    results: list[dict[str, Any]] = []
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


# A word in the heading of an article weighs most, one in the title of a division it stands
# in (titel, afdeling) more than one in its text; a word in a name a law is cited by more
# than one in its long title.
_BOOSTS: dict[str, dict[str, float]] = {
    "articles": {"heading": 4.0, "display_name": 2.0, "breadcrumb.title": 1.5},
    "instruments": {"aliases": 3.0, "short_title": 3.0, "citation_title": 2.0},
}


def _text_query(
    store: GraphStore,
    table: str,
    hit: str,
    tokens: list[str],
    fields: list[str],
    limit: int,
    *,
    joins: str = "",
    where: str = "",
    params: dict[str, Any] | None = None,
    live: bool = False,
    termed: list[list[str]] | None = None,
) -> Query:
    """The hits of *table* that hold every token in *fields*, the best ranked first (the
    key settles ties); *live* as ``_live_query``. *termed*: per token the rows that have
    it as a term (``_termed``), found too and ranked ``TERM_WEIGHT`` higher.

    Run it with ``store.query(..., indexes_only=True)``: its conditions and its rank read
    the large search columns, whose detoasting the planner does not count, so for a
    common word it would scan the whole table instead of using the indexes."""
    if live:
        return _live_query(
            table, hit, tokens, fields, limit, joins, where, params, termed
        )
    clause, clause_params = build_search_clause(table, tokens, fields, termed=termed)
    words = {k: v for k, v in clause_params.items() if k.startswith("_tok_")}
    rank, lateral, rank_params = bm25_sql(
        store, table, words, fields, _BOOSTS.get(table, {})
    )
    if termed:
        bonus = " + ".join(
            f"(doc.id = ANY(%(_termed_{i})s::text[]))::int" for i in range(len(tokens))
        )
        rank = f"({rank} + {TERM_WEIGHT} * ({bonus}))"
    # Ranked on the search columns alone; only the hits kept are read for their props (a
    # judgment's props hold its whole text, and every read of a json prop parses them).
    # The matches are found first, on their own (OFFSET 0 keeps the planner from walking
    # the key index for them when every rank is the same).
    statement = f"""
        SELECT {hit}
        FROM (
            SELECT doc.id, {rank} AS rank
            FROM (SELECT * FROM {table} doc WHERE {clause} {where} OFFSET 0) doc {lateral}
            ORDER BY rank DESC, doc.key
            LIMIT %(limit)s
        ) top
        JOIN {table} doc ON doc.id = top.id {joins}
        ORDER BY top.rank DESC, doc.key
        """
    return statement, {**clause_params, **rank_params, **(params or {}), "limit": limit}


# ── articles ─────────────────────────────────────────────────────────────────

_ARTICLE_FIELDS = [
    "display_name",
    "heading",
    "breadcrumb.title",
    "text",
    "article_number",
    "bwb_id",
]

# The instrument of an article: the first by key with its BWB id, else with its CELEX id.
_ARTICLE_INSTRUMENT = """
    LEFT JOIN LATERAL (
        SELECT i.props FROM instruments i
        WHERE doc.bwb_id IS NOT NULL AND i.bwb_id = doc.bwb_id
        ORDER BY i.key LIMIT 1
    ) by_bwb ON true
    LEFT JOIN LATERAL (
        SELECT i.props FROM instruments i
        WHERE doc.celex IS NOT NULL AND i.celex = doc.celex
        ORDER BY i.key LIMIT 1
    ) by_celex ON true
"""
_INSTRUMENT_PROPS = "coalesce(by_bwb.props, by_celex.props)"

_ARTICLE_HIT = f"""
    json_build_object(
        'id', doc.id, 'key', doc.key,
        'collection', 'articles', 'type', doc.type,
        'display_name', doc.props -> 'display_name',
        'snippet', left(coalesce(doc.props ->> 'text', ''), 200),
        'extra', json_build_object(
            'bwb_id', doc.props -> 'bwb_id',
            'celex', doc.props -> 'celex',
            'article_number', doc.props -> 'article_number',
            'heading', doc.props -> 'heading',
            'division_titles', (
                SELECT coalesce(json_agg(b -> 'title' ORDER BY n), '[]'::json)
                FROM json_array_elements(
                    CASE WHEN json_typeof(doc.props -> 'breadcrumb') = 'array'
                         THEN doc.props -> 'breadcrumb' ELSE '[]'::json END
                ) WITH ORDINALITY AS c(b, n)
                WHERE coalesce(json_typeof(b -> 'title'), 'null') <> 'null'
            ),
            'instrument_title', {
    _not_null(
        f"{_INSTRUMENT_PROPS} -> 'citation_title'", f"{_INSTRUMENT_PROPS} -> 'title'"
    )
},
            'citation_title', {_INSTRUMENT_PROPS} -> 'citation_title',
            'short_title', {_INSTRUMENT_PROPS} -> 'short_title'
        )
    )
"""


# An article whose case law calls it by a word of the query (``lg_article_terms``) ranks as
# much higher as a word in its heading would (BM25 of a rare word, boosted); at most
# ``TERMED`` of them per word, the first by id.
TERM_WEIGHT = 10.0
TERMED = 1_000

_TERMED_SQL = """
SELECT w.n::int AS n,
       coalesce(array_agg(t.article_id ORDER BY t.article_id)
                FILTER (WHERE t.article_id IS NOT NULL), '{}') AS ids
FROM unnest(%(forms)s::text[]) WITH ORDINALITY AS w(forms, n)
LEFT JOIN LATERAL (
    -- found through the index of the terms first (OFFSET 0), not by walking the keys in
    -- order until the cap
    SELECT a.article_id FROM (
        SELECT a.article_id FROM lg_article_terms a
        WHERE a.terms && lg_tokens(w.forms)
        OFFSET 0
    ) a
    ORDER BY a.article_id NULLS LAST
    LIMIT %(cap)s
) t ON true
GROUP BY w.n
ORDER BY w.n
"""


def _termed(store: GraphStore, tokens: list[str]) -> list[list[str]] | None:
    """Per token the articles that have it (or a form of it) as a term; None when none
    has any."""
    if not tokens:
        return None
    rows = store.query(
        _TERMED_SQL, {"forms": [word_forms(t) for t in tokens], "cap": TERMED}
    )
    termed = [list(row["ids"]) for row in rows]
    return termed if any(termed) else None


def _with_terms(
    hits: list[dict[str, Any]], tokens: list[str], termed: list[list[str]] | None
) -> list[dict[str, Any]]:
    """Each hit found by a term with ``extra.terms``: the words of the query it has as
    terms (the front end says where they come from: the case law)."""
    if termed:
        found = [set(ids) for ids in termed]
        for hit in hits:
            words = [
                t for t, ids in zip(tokens, found, strict=True) if hit["id"] in ids
            ]
            if words:
                hit["extra"]["terms"] = words
    return hits


def _search_articles(
    store: GraphStore,
    tokens: list[str],
    notation: Notation | None,
    limit: int,
    live: bool = False,
    period: Period = NO_PERIOD,
) -> list[dict[str, Any]]:
    termed = _termed(store, tokens)
    in_period = period.where("articles")
    text = _text_query(
        store,
        "articles",
        _ARTICLE_HIT,
        tokens,
        _ARTICLE_FIELDS,
        limit,
        joins=_ARTICLE_INSTRUMENT,
        where=in_period,
        params=period.params(),
        live=live,
        termed=termed,
    )
    if notation is None or notation.kind != "article":
        hits = list(store.query(*text, indexes_only=True))[:limit]
        return _with_terms(hits, tokens, termed)

    # The law is named: the article is one key. It is not: every law with that number.
    keys = [make_node_key(a.law_id, a.number) for a in notation.articles if a.law_id]
    if keys:
        precise: Query = (
            f"""
            SELECT {_ARTICLE_HIT} FROM articles doc {_ARTICLE_INSTRUMENT}
            WHERE doc.key = ANY(%(keys)s) {in_period}
            ORDER BY array_position(%(keys)s::text[], doc.key)
            LIMIT %(limit)s
            """,
            {"keys": keys, "limit": limit, **period.params()},
        )
    else:
        precise = (
            f"""
            SELECT {_ARTICLE_HIT} FROM articles doc {_ARTICLE_INSTRUMENT}
            WHERE doc.article_number = ANY(%(numbers)s) {in_period}
            ORDER BY doc.bwb_id NULLS FIRST, doc.key
            LIMIT %(limit)s
            """,
            {
                "numbers": [a.number for a in notation.articles],
                "limit": limit,
                **period.params(),
            },
        )
    return _with_terms(_two_phase_search(store, precise, text, limit), tokens, termed)


# ── instruments ──────────────────────────────────────────────────────────────

_INSTRUMENT_FIELDS = [
    "title",
    "citation_title",
    "official_title",
    "display_name",
    "short_title",
    "aliases",
    "bwb_id",
]
_INSTRUMENT_HIT = f"""
    json_build_object(
        'id', doc.id, 'key', doc.key,
        'collection', 'instruments', 'type', doc.type,
        'display_name', {
    _not_null(
        "doc.props -> 'citation_title'",
        "doc.props -> 'display_name'",
        "doc.props -> 'title'",
    )
},
        'snippet', left(coalesce(doc.props ->> 'title', ''), 200),
        'extra', json_build_object(
            'bwb_id', doc.props -> 'bwb_id',
            'citation_title', doc.props -> 'citation_title',
            'short_title', doc.props -> 'short_title',
            'aliases', doc.props -> 'aliases'
        )
    )
"""


def _search_instruments(
    store: GraphStore,
    q: str,
    tokens: list[str],
    limit: int,
    live: bool = False,
    period: Period = NO_PERIOD,
) -> list[dict[str, Any]]:
    """Instruments whose alias or short title is the whole query first (``Boek 6 BW``,
    ``BW``), then those that hold its words."""
    precise: Query = (
        f"""
        SELECT {_INSTRUMENT_HIT} FROM instruments doc
        WHERE (doc.{search_column("aliases", "norm")} @> ARRAY[lg_fold(%(name)s)]
           OR doc.{search_column("short_title", "norm")} @> ARRAY[lg_fold(%(name)s)])
          {period.where("instruments")}
        ORDER BY doc.citation_title NULLS FIRST, doc.key
        LIMIT %(limit)s
        """,
        {"name": _folded(q), "limit": limit, **period.params()},
    )
    text = _text_query(
        store,
        "instruments",
        _INSTRUMENT_HIT,
        tokens,
        _INSTRUMENT_FIELDS,
        limit,
        where=period.where("instruments"),
        params=period.params(),
        live=live,
    )
    return _two_phase_search(store, precise, text, limit, precise_score=None)


# ── judgments ────────────────────────────────────────────────────────────────

_JUDGMENT_FIELDS = ["display_name", "names", "summary", "ecli", "appno"]
_JUDGMENT_HIT = """
    json_build_object(
        'id', doc.id, 'key', doc.key,
        'collection', 'judgments', 'type', doc.type,
        'display_name', doc.props -> 'display_name',
        'snippet', left(coalesce(doc.props ->> 'summary', ''), 200),
        'extra', json_build_object(
            'ecli', doc.props -> 'ecli',
            'appno', doc.props -> 'appno',
            'names', doc.props -> 'names'
        )
    )
"""
_ECLI_HIT = """
    json_build_object(
        'id', doc.id, 'key', doc.key,
        'collection', 'judgments', 'type', doc.type,
        'display_name', doc.props -> 'display_name',
        'snippet', left(coalesce(doc.props ->> 'summary', ''), 200),
        'extra', json_build_object('ecli', doc.props -> 'ecli')
    )
"""


def _search_judgments(
    store: GraphStore,
    tokens: list[str],
    notation: Notation | None,
    limit: int,
    q: str = "",
    period: Period = NO_PERIOD,
) -> list[dict[str, Any]]:
    text = _text_query(
        store,
        "judgments",
        _JUDGMENT_HIT,
        tokens,
        _JUDGMENT_FIELDS,
        limit,
        where=period.where("judgments"),
        params=period.params(),
    )
    if notation is not None and notation.kind == "ecli":
        ecli: Query = (
            f"""
            SELECT {_ECLI_HIT} FROM judgments doc
            WHERE doc.ecli = %(ecli)s {period.where("judgments")}
            ORDER BY doc.key
            LIMIT %(limit)s
            """,
            {"ecli": notation.identifier, "limit": limit, **period.params()},
        )
        return _two_phase_search(store, ecli, text, limit)

    # The query may be the name of a judgment ("Urgenda", "Lindenbaum/Cohen"): those first,
    # the latest decision first (of one case: the highest court), a translation after the
    # judgment it translates. The judgments of that name are found first, on their own
    # (OFFSET 0): the planner expects 0.5% of the rows to hold any name, and would walk the
    # index of the dates for them (on the full graph every row, 2.6 s, for a name none has).
    name: Query = (
        f"""
        SELECT {_JUDGMENT_HIT}
        FROM (
            SELECT * FROM judgments doc
            WHERE doc.{search_column("names", "norm")} @> ARRAY[lg_fold(%(name)s)]
              {period.where("judgments")}
            OFFSET 0
        ) doc
        ORDER BY doc.date_eff DESC NULLS LAST,
                 coalesce(json_typeof(doc.props -> 'translation_of'), 'null') <> 'null',
                 doc.key
        LIMIT %(limit)s
        """,
        {"name": q.strip(), "limit": limit, **period.params()},
    )
    return _two_phase_search(store, name, text, limit)


# ── dossiers, committees, documents ──────────────────────────────────────────

_KIND = "AND lower(doc.props ->> 'kind') = ANY(%(kind_filter)s)"
# The chamber of a document from its labels, as everywhere (``chamber_sql``): null for a
# Staatsblad or Staatscourant publication.
_CHAMBER = chamber_sql("doc")


def _search_dossiers(
    store: GraphStore,
    tokens: list[str],
    kinds: list[str] | None,
    limit: int,
    live: bool = False,
    period: Period = NO_PERIOD,
) -> list[dict[str, Any]]:
    hit = f"""
        json_build_object(
            'id', doc.id, 'key', doc.key,
            'collection', 'dossiers', 'type', doc.type,
            'display_name', {_not_null("doc.props -> 'title'", "doc.props -> 'display_name'")},
            'snippet', doc.props -> 'label',
            'extra', json_build_object(
                'number', doc.props -> 'label',
                'kind', doc.props -> 'kind',
                'current_phase', doc.props -> 'current_phase',
                'closed', doc.props -> 'closed',
                'outcome', doc.props -> 'outcome',
                'title', doc.props -> 'title'
            )
        )
    """
    query = _text_query(
        store,
        "dossiers",
        hit,
        tokens,
        ["title", "display_name", "number"],
        limit,
        where=(_KIND if kinds else "") + period.where("dossiers"),
        params={"kind_filter": [k.lower() for k in kinds or []], **period.params()},
        live=live,
    )
    hits = list(store.query(*query, indexes_only=True))
    for hit in hits:
        # the name the dossier goes by, as /api/dossiers gives it ("Wet betaalbare huur")
        extra = hit["extra"]
        extra["short_title"] = short_title(extra.pop("title", None))
    return hits


def _search_committees(
    store: GraphStore, tokens: list[str], limit: int, live: bool = False
) -> list[dict[str, Any]]:
    hit = """
        json_build_object(
            'id', doc.id, 'key', doc.key,
            'collection', 'committees', 'type', doc.type,
            'display_name', doc.props -> 'name',
            'snippet', doc.props -> 'abbreviation',
            'extra', json_build_object(
                'slug', doc.props -> 'slug', 'abbreviation', doc.props -> 'abbreviation'
            )
        )
    """
    query = _text_query(
        store, "committees", hit, tokens, ["name", "abbreviation"], limit, live=live
    )
    return list(store.query(*query, indexes_only=True))


def _search_documents(
    store: GraphStore,
    tokens: list[str],
    kinds: list[str] | None,
    limit: int,
    live: bool = False,
    period: Period = NO_PERIOD,
) -> list[dict[str, Any]]:
    # Hydrated PDF text isn't indexed (~500 KB rows are too bulky for sub-200-ms search);
    # identifier and title fields cover the UI use cases.
    hit = f"""
        json_build_object(
            'id', doc.id, 'key', doc.key,
            'collection', 'documents', 'type', doc.type,
            'display_name', {_not_null("doc.props -> 'title'", "doc.props -> 'display_name'")},
            'snippet', doc.props -> 'kind',
            'extra', json_build_object(
                'kind', doc.props -> 'kind',
                'external_id', doc.props -> 'external_id',
                'dossier_number', CASE WHEN json_typeof(doc.props -> 'dossier_numbers') = 'array'
                                       THEN doc.props -> 'dossier_numbers' -> 0 END,
                'sequence', doc.props -> 'sequence',
                'number', CASE {_CHAMBER}
                              WHEN 'EK' THEN doc.props ->> 'number'
                              WHEN 'TK' THEN doc.props ->> 'sequence'
                          END,
                'date', doc.props -> 'date',
                'chamber', {_CHAMBER}
            ),
            -- what its readable address is built from: its own dossier, not a label
            'path_props', json_build_object(
                'dossier_number', doc.dossier_number,
                'dossier_suffix', doc.props -> 'dossier_suffix',
                'sequence', doc.props -> 'sequence',
                'number', doc.props -> 'number'
            )
        )
    """
    query = _text_query(
        store,
        "documents",
        hit,
        tokens,
        ["display_name", "title", "external_id"],
        limit,
        where=(_KIND if kinds else "") + period.where("documents"),
        params={"kind_filter": [k.lower() for k in kinds or []], **period.params()},
        live=live,
    )
    return list(store.query(*query, indexes_only=True))


# ── members and factions: every word in their names ─────────────────────────


def _all_words(
    tokens: list[str], words: str = "doc.search_names"
) -> tuple[str, dict[str, Any]]:
    """Every token is a part of *words* (the names of a member or faction, the words of a
    cabinet or commitment: lower case): a trigram lookup each."""
    params = {f"_word_{i}": token for i, token in enumerate(tokens)}
    condition = " AND ".join(
        f"{words} LIKE '%%' || lg_like(%({name})s) || '%%'" for name in params
    )
    return condition, params


def _all_words_folded(tokens: list[str], folded: str) -> tuple[str, dict[str, Any]]:
    """``_all_words``, and a token also found in the *folded* names, both folded as the
    search folds them (``lg_fold``: ``yesilgoz`` finds Yeşilgöz), on a trigram index of
    their own (``schema._search_indexes``): ``search_names`` is lower case only."""
    params = {f"_word_{i}": token for i, token in enumerate(tokens)}
    condition = " AND ".join(
        f"(doc.search_names LIKE '%%' || lg_like(%({name})s) || '%%'"
        f" OR {folded} LIKE '%%' || lg_like(lg_fold(%({name})s)) || '%%')"
        for name in params
    )
    return condition, params


def _search_members(
    store: GraphStore, tokens: list[str], limit: int
) -> list[dict[str, Any]]:
    # a member's own name folded: the factions of a timeline are found as they are written
    condition, params = _all_words_folded(tokens, "lg_fold(doc.name)")
    statement = f"""
        SELECT json_build_object(
            'id', doc.id, 'key', doc.key,
            'collection', 'members', 'type', doc.type,
            'display_name', doc.props -> 'name',
            'snippet', doc.props -> 'party',
            'extra', json_build_object(
                'party', doc.props -> 'party', 'active', doc.props -> 'active'
            )
        )
        FROM members doc
        WHERE {condition}
        ORDER BY doc.active DESC NULLS LAST, doc.name NULLS FIRST, doc.key
        LIMIT %(limit)s
        """
    return list(store.query(statement, {**params, "limit": limit}))


def _search_factions(
    store: GraphStore, tokens: list[str], limit: int
) -> list[dict[str, Any]]:
    condition, params = _all_words_folded(tokens, "lg_fold(doc.search_names)")
    statement = f"""
        SELECT json_build_object(
            'id', doc.id, 'key', doc.key,
            'collection', 'factions', 'type', doc.type,
            'display_name', doc.props -> 'name',
            'snippet', doc.props -> 'abbreviation',
            'extra', json_build_object(
                'abbreviation', doc.props -> 'abbreviation',
                'seats', doc.props -> 'seats',
                'active', doc.props -> 'active'
            )
        )
        FROM factions doc
        WHERE {condition}
        ORDER BY doc.active DESC NULLS LAST, coalesce(doc.seats, 0) DESC,
                 doc.name NULLS FIRST, doc.key
        LIMIT %(limit)s
        """
    return list(store.query(statement, {**params, "limit": limit}))


def _search_cabinets(
    store: GraphStore, tokens: list[str], limit: int
) -> list[dict[str, Any]]:
    """Every word in the name of the cabinet (``kabinet-Schoof``), newest first."""
    condition, params = _all_words(tokens, search_words("cabinets", "doc"))
    statement = f"""
        SELECT json_build_object(
            'id', doc.id, 'key', doc.key,
            'collection', 'cabinets', 'type', doc.type,
            'display_name', doc.props -> 'name',
            'snippet', doc.props -> 'from_date',
            'extra', json_build_object(
                'from_date', doc.props -> 'from_date',
                'to_date', doc.props -> 'to_date'
            )
        )
        FROM cabinets doc
        WHERE {condition}
        ORDER BY lg_str(doc.props -> 'from_date') DESC NULLS LAST, doc.key
        LIMIT %(limit)s
        """
    return list(store.query(statement, {**params, "limit": limit}))


def _search_commitments(
    store: GraphStore, tokens: list[str], limit: int, period: Period = NO_PERIOD
) -> list[dict[str, Any]]:
    """Every word in the text or the number of the commitment (``TZ202609-011``), newest
    first."""
    condition, params = _all_words(tokens, search_words("commitments", "doc"))
    statement = f"""
        SELECT json_build_object(
            'id', doc.id, 'key', doc.key,
            'collection', 'commitments', 'type', doc.type,
            'display_name', doc.props -> 'display_name',
            'snippet', doc.props -> 'number',
            'extra', json_build_object(
                'number', doc.props -> 'number',
                'made_on', doc.props -> 'made_on',
                'status', doc.props -> 'status',
                'minister_name', doc.props -> 'minister_name',
                'cabinet', doc.props -> 'cabinet',
                'ministry', doc.props -> 'ministry'
            )
        )
        FROM commitments doc
        WHERE {condition} {period.where("commitments")}
        ORDER BY doc.made_on DESC NULLS LAST, doc.key
        LIMIT %(limit)s
        """
    return list(store.query(statement, {**params, **period.params(), "limit": limit}))


# Words that name the type of a vote rather than what it was on: "stemming abortus" asks
# for the votes on abortion, and no subject holds "stemming".
_VOTE_WORDS = frozenset({"stemming", "stemmingen", "besluit", "besluiten"})


def _search_decisions(
    store: GraphStore, tokens: list[str], limit: int, period: Period = NO_PERIOD
) -> list[dict[str, Any]]:
    """Every word (but those of ``_VOTE_WORDS``) in the subject or the kind of a vote,
    newest first; nothing when only such words are asked."""
    words = [t for t in tokens if t not in _VOTE_WORDS]
    if not words:
        return []
    condition, params = _all_words(words, search_words("decisions", "doc"))
    statement = f"""
        SELECT json_build_object(
            'id', doc.id, 'key', doc.key,
            'collection', 'decisions', 'type', doc.type,
            'display_name', doc.props -> 'display_name',
            'snippet', doc.props -> 'subject',
            'extra', json_build_object(
                'date', doc.props -> 'date',
                'kind', doc.props -> 'kind',
                'passed', doc.props -> 'passed',
                'chamber', doc.props -> 'chamber',
                'dossier_numbers', doc.props -> 'dossier_numbers'
            )
        )
        FROM decisions doc
        WHERE {condition} {period.where("decisions")}
        ORDER BY doc.date DESC NULLS LAST, doc.key
        LIMIT %(limit)s
        """
    return list(store.query(statement, {**params, **period.params(), "limit": limit}))


# ── Ranking ───────────────────────────────────────────────────────────────────

# What identifies a hit, besides its key: the fields of ``extra`` that are identifiers.
_IDENTIFIER_FIELDS = (
    "bwb_id",
    "celex",
    "ecli",
    "appno",
    "number",
    "external_id",
    "dossier_number",
    "abbreviation",
    "short_title",
    "slug",
)
_NAME_FIELDS = ("citation_title", "instrument_title", "heading")
# The names of a hit that are lists: the aliases of an instrument.
_NAME_LIST_FIELDS = ("aliases",)
# What places a hit without naming it: the titles of the divisions an article stands in.
_CONTEXT_LIST_FIELDS = ("division_titles",)


# The marks ``lg_fold`` takes off a letter after NFD (U+0300-U+036F).
_ACCENTS = re.compile("[\u0300-\u036f]")


def _folded(value: Any) -> str:
    """*value* as ``lg_fold`` folds it (lower case, without accents: "yesilgoz" is part of
    "Yeşilgöz-Zegerius"), its spaces one each."""
    if not value:
        return ""
    plain = unicodedata.normalize("NFD", str(value).lower())
    plain = unicodedata.normalize("NFC", _ACCENTS.sub("", plain))
    return " ".join(plain.split())


def _folded_list(extra: Mapping[str, Any], fields: tuple[str, ...]) -> list[str]:
    return [
        _folded(value)
        for field in fields
        for value in extra.get(field) or ()
        if isinstance(value, str) and value.strip()
    ]


def score_hit(query: str, hit: Mapping[str, Any]) -> float:
    """The rank tier of *hit* for *query*: identifier, whole name, name prefix, name part.

    Pure: compares the query with the key, the identifiers and the names the hit carries
    (its display name, citation title, heading and aliases). A query that is part of the
    title of a division an article stands in counts as part of its name.
    """
    wanted = _folded(query)
    if not wanted:
        return SCORE_WORDS
    extra = hit.get("extra") or {}
    identifiers = {
        _folded(hit.get("key")),
        *(_folded(extra.get(field)) for field in _IDENTIFIER_FIELDS),
    }
    if wanted in identifiers or make_node_key(wanted) == hit.get("key"):
        return SCORE_IDENTIFIER
    names = [
        _folded(hit.get("display_name")),
        *(_folded(extra.get(field)) for field in _NAME_FIELDS),
        *(_folded(name) for name in extra.get("names") or []),
    ]
    names = [n for n in names if n] + _folded_list(extra, _NAME_LIST_FIELDS)
    if wanted in names:
        return SCORE_TITLE
    if any(n.startswith(wanted) for n in names):
        return SCORE_PREFIX
    words = wanted.split()
    context = _folded_list(extra, _CONTEXT_LIST_FIELDS)
    if any(all(w in n for w in words) for n in names + context):
        return SCORE_CONTAINS
    return SCORE_WORDS


def rank_hits(query: str, hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """*hits* with a ``score`` each (a hit that has one keeps it), best first."""
    scored = [{**h, "score": h.get("score", score_hit(query, h))} for h in hits]
    return sorted(scored, key=lambda h: -h["score"])


# ── Main search dispatcher ────────────────────────────────────────────────────


def search_all(
    store: GraphStore,
    *,
    q: str,
    types: list[str],
    kinds: list[str] | None = None,
    limit: int = 20,
    period: Period = NO_PERIOD,
) -> dict[str, list[dict[str, Any]]]:
    """Full-text search across requested entity types (of *period*: ``Period``).

    Returns a dict keyed by type name with a list of hit dicts each containing
    {id, key, collection, type, display_name, snippet, extra, score}, best score first.

    Every token must appear — AND semantics: in the searched fields of the indexed types,
    in the names of members and factions.
    """
    tokens = tokenize_search_query(q)
    if not tokens:
        return {t: [] for t in types}

    notation = _notation(store, q, types)
    searches = _full_searches(store, q, tokens, notation, kinds, limit, period)
    wanted = [t for t in types if t in searches]
    # The types are searched side by side, each on a connection of its own: the answer
    # takes as long as the slowest type, not as long as all of them.
    found = side_by_side(_SEARCHES, [searches[t] for t in wanted])
    return {t: rank_hits(q, hits) for t, hits in zip(wanted, found, strict=True)}


Searches = dict[str, Callable[[], list[dict[str, Any]]]]


def _notation(
    store: GraphStore, q: str, types: list[str], wait: float = STALE_WAIT
) -> Notation | None:
    """The citation *q* is, when articles or judgments are searched; None also when the
    parser is not there within *wait* seconds (``kept_notation_parser``)."""
    if not {"articles", "judgments"} & set(types):
        return None
    parser = kept_notation_parser(store, wait)
    return parser.parse(q) if parser else None


def _full_searches(
    store: GraphStore,
    q: str,
    tokens: list[str],
    notation: Notation | None,
    kinds: list[str] | None,
    limit: int,
    period: Period = NO_PERIOD,
) -> Searches:
    """The search of each type, ranked by its words; with a *period* only the types that
    have a date of their own, in it."""
    searches: Searches = {
        "articles": lambda: _search_articles(
            store, tokens, notation, limit, period=period
        ),
        "instruments": lambda: _search_instruments(
            store, q, tokens, limit, period=period
        ),
        "judgments": lambda: _search_judgments(
            store, tokens, notation, limit, q, period
        ),
        "dossiers": lambda: _search_dossiers(
            store, tokens, kinds, limit, period=period
        ),
        "committees": lambda: _search_committees(store, tokens, limit),
        "members": lambda: _search_members(store, tokens, limit),
        "factions": lambda: _search_factions(store, tokens, limit),
        "documents": lambda: _search_documents(
            store, tokens, kinds, limit, period=period
        ),
        "cabinets": lambda: _search_cabinets(store, tokens, limit),
        "commitments": lambda: _search_commitments(store, tokens, limit, period),
        "decisions": lambda: _search_decisions(store, tokens, limit, period),
    }
    return _in_period(searches, period)


def _in_period(searches: Searches, period: Period) -> Searches:
    """*searches*, a type without a date of its own finding nothing within a *period*."""
    return {
        table: search if period.keeps(table) else (lambda: [])
        for table, search in searches.items()
    }


def _live_searches(
    store: GraphStore,
    q: str,
    tokens: list[str],
    notation: Notation | None,
    kinds: list[str] | None,
    limit: int,
    period: Period = NO_PERIOD,
) -> Searches:
    """The search of each type while typing: nothing ranked by its words; with a
    *period* only the types that have a date of their own, in it."""
    searches: Searches = {
        "articles": lambda: _search_articles(
            store, tokens, notation, limit, True, period
        ),
        "instruments": lambda: _search_instruments(
            store, q, tokens, limit, True, period
        ),
        # a judgment the query names, else the newest that hold its words
        "judgments": lambda: (
            _search_judgments_live(store, tokens, notation, limit, q, period)
            or _judgments_with_words(store, tokens, limit, q, period)
        ),
        "dossiers": lambda: _search_dossiers(store, tokens, kinds, limit, True, period),
        "committees": lambda: _search_committees(store, tokens, limit, True),
        "members": lambda: _search_members(store, tokens, limit),
        "factions": lambda: _search_factions(store, tokens, limit),
        "documents": lambda: _search_documents(
            store, tokens, kinds, limit, True, period
        ),
        "cabinets": lambda: _search_cabinets(store, tokens, limit),
        "commitments": lambda: _search_commitments(store, tokens, limit, period),
        "decisions": lambda: _search_decisions(store, tokens, limit, period),
    }
    return _in_period(searches, period)


# How long one type of the full search may rank (seconds): past it, the type answers what
# its live search finds within ``FALLBACK_BUDGET``, and is named in ``partial``, instead
# of the whole request answering 503 at its deadline.
FULL_BUDGET = 3.0
FALLBACK_BUDGET = 1.0


def search_full(
    store: GraphStore,
    *,
    q: str,
    types: list[str],
    kinds: list[str] | None = None,
    limit: int = 20,
    period: Period = NO_PERIOD,
) -> tuple[dict[str, list[dict[str, Any]]], set[str]]:
    """``search_all`` within ``FULL_BUDGET`` per type: a type that takes longer answers
    its live search (``search_live``: the judgments by name and display name, the most
    cited first, else the newest that hold the words; the other types by the start of a
    word of a name, without a rank).
    Returns the hits per type and the types that fell back."""
    tokens = tokenize_search_query(q)
    if not tokens:
        return {t: [] for t in types}, set()
    notation = _notation(store, q, types)
    full = _full_searches(store, q, tokens, notation, kinds, limit, period)
    live = _live_searches(store, q, tokens, notation, kinds, limit, period)
    wanted = [t for t in types if t in full]
    found = side_by_side(
        _SEARCHES,
        [functools.partial(_full_or_live, full[t], live[t]) for t in wanted],
    )
    hits = {t: rank_hits(q, rows) for t, (rows, _) in zip(wanted, found, strict=True)}
    partial = {t for t, (_, cut) in zip(wanted, found, strict=True) if cut}
    return hits, partial


def _full_or_live(
    full: Callable[[], list[dict[str, Any]]],
    live: Callable[[], list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], bool]:
    """The hits of *full* within ``FULL_BUDGET``; past it, those of *live* within
    ``FALLBACK_BUDGET``, cut off."""
    rows, cut = _within_budget(full, FULL_BUDGET)
    if not cut:
        return rows, False
    return _within_budget(live, FALLBACK_BUDGET)[0], True


_SEARCHES = ThreadPoolExecutor(max_workers=4, thread_name_prefix="search")


# ── Live search: while typing ──────────────────────────────────────────────────

# How long one type of a live search may read (seconds): what it has not found by then, it
# answers empty and ``partial`` (the full search after Enter has it).
LIVE_BUDGET = 0.25
# The judgments a live search looks for need this many characters: a part of a name or
# number of fewer is in too many.
LIVE_MIN_JUDGMENT = 3


def search_live(
    store: GraphStore,
    *,
    q: str,
    types: list[str],
    kinds: list[str] | None = None,
    limit: int = 10,
    period: Period = NO_PERIOD,
) -> tuple[dict[str, list[dict[str, Any]]], set[str]]:
    """``search_all`` while typing: all types within ``LIVE_BUDGET``, nothing ranked by
    its words (``_live_query``), and the judgments without their summaries: an ECLI, the
    name of a judgment, then the judgments whose display name (its court, date and case
    number) holds every word, the most cited first; when none does (a subject:
    ``onrechtmatige daad``), the newest that hold the words. Returns the hits per type and
    the types cut off at their budget."""
    tokens = tokenize_search_query(q)
    if not tokens:
        return {t: [] for t in types}, set()
    with stale_wait(LIVE_STALE_WAIT):
        return _search_live(store, q, tokens, types, kinds, limit, period)


# What a search while typing waits for a kept answer of a new data version (the parser of
# citations reads every instrument: seconds after a poll) before it takes the one before.
LIVE_STALE_WAIT = 0.05


def _search_live(
    store: GraphStore,
    q: str,
    tokens: list[str],
    types: list[str],
    kinds: list[str] | None,
    limit: int,
    period: Period = NO_PERIOD,
) -> tuple[dict[str, list[dict[str, Any]]], set[str]]:
    searches = _live_searches(
        store,
        q,
        tokens,
        _notation(store, q, types, LIVE_STALE_WAIT),
        kinds,
        limit,
        period,
    )
    wanted = [t for t in types if t in searches]
    # one budget for them all: a type that waited for a thread (``side_by_side`` runs those
    # for which none is free one after another) has what is left of it
    ends = time.monotonic() + LIVE_BUDGET
    found = side_by_side(
        _SEARCHES,
        [functools.partial(_within_live_budget, searches[t], ends) for t in wanted],
    )
    hits = {t: rank_hits(q, rows) for t, (rows, _) in zip(wanted, found, strict=True)}
    partial = {t for t, (_, cut) in zip(wanted, found, strict=True) if cut}
    return hits, partial


def _within_live_budget(
    search: Callable[[], list[dict[str, Any]]], ends: float
) -> tuple[list[dict[str, Any]], bool]:
    """``_within_budget`` with what is left until *ends* (``time.monotonic``)."""
    return _within_budget(search, max(0.0, ends - time.monotonic()))


# The rows a live search orders at most: a common word is in far more, and the first found
# stand for them (the full search after Enter ranks them all).
LIVE_CANDIDATES = 2_000
# The order of a live search per table, without a rank: what stands out first.
_LIVE_ORDER = {
    "articles": "doc.inbound_citation_count DESC NULLS LAST, doc.key",
    "instruments": "doc.article_count DESC NULLS LAST, doc.key",
    "dossiers": "doc.last_activity DESC NULLS LAST, doc.key DESC",
    "documents": "doc.date DESC NULLS LAST, doc.key DESC",
    "committees": "doc.key",
    "judgments": "doc.date_eff DESC NULLS LAST, doc.key DESC",
}


# The query typed so far as the start of a folded value (``_live_query``).
_LIVE_START = "lg_like(lg_fold(%(_live_q)s)) || '%%'"


def _live_query(
    table: str,
    hit: str,
    tokens: list[str],
    fields: list[str],
    limit: int,
    joins: str = "",
    where: str = "",
    params: dict[str, Any] | None = None,
    termed: list[list[str]] | None = None,
) -> Query:
    """``_text_query`` while typing: no word counted (the df of BM25) and none ranked.
    Every token is a word of *fields*, a whole value of one, or, from three characters,
    the start of a word of a name or title (``stik``: Stikstofwet); of the first
    ``LIVE_CANDIDATES`` found, those whose name or title starts with the query first (as
    ``score_hit``), then those first in ``_LIVE_ORDER``."""
    clause, clause_params = _live_clause(table, tokens, fields, termed)
    starts = " OR ".join(
        f"doc.{column} LIKE {_LIVE_START} OR doc.{column} LIKE '%%' || chr(31) || {_LIVE_START}"
        for column in (
            search_column(f, "ngram")
            for f in fields
            if "ngram" in SEARCH_FIELDS[table][f]
        )
    )
    order = f"({starts or 'false'}) DESC, {_LIVE_ORDER[table]}"
    candidates = (
        f"SELECT * FROM {table} doc WHERE {clause} {where} LIMIT %(candidates)s"
    )
    if termed:
        # the rows that have a token as a term are candidates whatever the first found,
        # by their keys, and come after those whose name starts with the query
        clause_params["_termed"] = sorted({row for rows in termed for row in rows})
        order = (
            f"({starts or 'false'}) DESC, doc.id = ANY(%(_termed)s::text[]) DESC, "
            + (_LIVE_ORDER[table])
        )
        candidates = (
            f"SELECT doc.* FROM ("
            f"(SELECT doc.id FROM {table} doc WHERE {clause} {where}"
            f" LIMIT %(candidates)s) UNION"
            f" SELECT doc.id FROM {table} doc"
            f" WHERE doc.id = ANY(%(_termed)s::text[]) AND {clause} {where}"
            f") found JOIN {table} doc ON doc.id = found.id"
        )
    # ordered on their ids and columns alone; only the hits kept are read for their props
    statement = f"""
        SELECT {hit}
        FROM (
            SELECT doc.id, row_number() OVER (ORDER BY {order}) AS n
            FROM ({candidates}) doc
            ORDER BY n
            LIMIT %(limit)s
        ) top
        JOIN {table} doc ON doc.id = top.id {joins}
        ORDER BY top.n
        """
    return statement, {
        **clause_params,
        **(params or {}),
        "_live_q": " ".join(tokens),
        "candidates": LIVE_CANDIDATES,
        "limit": limit,
    }


def _live_clause(
    table: str,
    tokens: list[str],
    fields: list[str],
    termed: list[list[str]] | None = None,
) -> tuple[str, dict[str, Any]]:
    """The condition of ``_live_query``: each an index lookup, none a part of a value
    within a word (``tikst``), which a short part finds in a large share of the rows."""
    params: dict[str, Any] = {}
    parts: list[str] = []
    for i, token in enumerate(tokens):
        word = f"_tok_{i}"
        params[word] = token
        per_field = []
        for field in fields:
            analyzers = SEARCH_FIELDS[table][field]
            if "text" in analyzers:
                # every word the token holds (``20/325``: 20 and 325), not any of them;
                # a token of no word (a stop word) holds none
                per_field.append(
                    f"(cardinality(lg_tokens(%({word})s)) > 0"
                    f" AND doc.{search_column(field, 'text')} @> lg_tokens(%({word})s))"
                )
            if "norm" in analyzers:
                per_field.append(
                    f"doc.{search_column(field, 'norm')} @> ARRAY[lg_fold(%({word})s)]"
                )
            if "ngram" in analyzers and len(token) >= 3:
                column = f"doc.{search_column(field, 'ngram')}"
                start = f"lg_like(lg_fold(%({word})s)) || '%%'"
                per_field += [
                    f"{column} LIKE {start}",
                    f"{column} LIKE '%% ' || {start}",
                    f"{column} LIKE '%%' || chr(31) || {start}",
                ]
        if termed:
            params[f"_termed_{i}"] = termed[i]
            per_field.append(f"doc.id = ANY(%(_termed_{i})s::text[])")
        parts.append("(" + " OR ".join(per_field or ["false"]) + ")")
    return " AND ".join(parts) or "true", params


def _within_budget(
    search: Callable[[], list[dict[str, Any]]], budget: float | None = None
) -> tuple[list[dict[str, Any]], bool]:
    """The hits of *search* within *budget* seconds (``LIVE_BUDGET`` without one; or what
    the request has left); none and cut off when it takes longer. A computation of the
    cache it waited for goes on."""
    budget = LIVE_BUDGET if budget is None else budget
    left = read_time_left()
    token = set_read_deadline(budget if left is None else min(budget, left))
    try:
        return search(), False
    except ReadTimedOut:
        return [], True
    finally:
        reset_read_deadline(token)


def _judgments_with_words(
    store: GraphStore,
    tokens: list[str],
    limit: int,
    q: str,
    period: Period = NO_PERIOD,
) -> list[dict[str, Any]]:
    """The judgments that hold every word (in their summary, name or display name), the
    newest first of the first ``LIVE_CANDIDATES`` found, without a rank (``_live_query``);
    none for a query shorter than ``LIVE_MIN_JUDGMENT``, as by name."""
    if len(q.strip()) < LIVE_MIN_JUDGMENT:
        return []
    return list(
        store.query(
            *_live_query(
                "judgments",
                _JUDGMENT_HIT,
                tokens,
                _JUDGMENT_FIELDS,
                limit,
                where="AND doc.stub IS NOT TRUE AND doc.same_as IS NULL"
                + period.where("judgments"),
                params=period.params(),
            ),
            indexes_only=True,
        )
    )


def _search_judgments_live(
    store: GraphStore,
    tokens: list[str],
    notation: Notation | None,
    limit: int,
    q: str,
    period: Period = NO_PERIOD,
) -> list[dict[str, Any]]:
    """The judgments a typed query names, without ranking a summary: an ECLI; a judgment
    whose name holds the query (``Urgenda``, ``Lindenbaum``); then those whose display name
    holds every word of three characters or more, the most cited first."""
    if len(q.strip()) < LIVE_MIN_JUDGMENT:
        return []
    if notation is not None and notation.kind == "ecli":
        return list(
            store.query(
                f"SELECT {_ECLI_HIT} FROM judgments doc WHERE doc.ecli = %(ecli)s"
                f"{period.where('judgments')} ORDER BY doc.key LIMIT %(limit)s",
                {"ecli": notation.identifier, "limit": limit, **period.params()},
            )
        )
    words = [t for t in tokens if len(t) >= LIVE_MIN_JUDGMENT]
    if not words:
        return []
    params: dict[str, Any] = {f"_w{n}": w for n, w in enumerate(words)}
    params["limit"] = limit
    params.update(period.params())
    holds = " AND ".join(
        f"doc.{{column}} LIKE '%%' || lg_like(lg_fold(%(_w{n})s)) || '%%'"
        for n in range(len(words))
    )
    params["candidates"] = LIVE_CANDIDATES
    found: list[dict[str, Any]] = []
    for column in (
        search_column("names", "ngram"),
        search_column("display_name", "ngram"),
    ):
        # the first ``LIVE_CANDIDATES`` found, then ordered: the index of the citations
        # would be walked for a part the planner thinks common, every row for a rare one
        statement = f"""
            SELECT {_JUDGMENT_HIT}
            FROM (
                SELECT doc.id, row_number() OVER (
                    ORDER BY doc.inbound_citation_count DESC NULLS LAST, doc.key DESC
                ) AS n
                FROM (
                    SELECT * FROM judgments doc
                    WHERE doc.stub IS NOT TRUE AND doc.same_as IS NULL
                      AND {holds.format(column=column)} {period.where("judgments")}
                    LIMIT %(candidates)s
                ) doc
                ORDER BY n
                LIMIT %(limit)s
            ) top
            JOIN judgments doc ON doc.id = top.id
            ORDER BY top.n
            """
        seen = {hit["id"] for hit in found}
        found += [
            hit for hit in store.query(statement, params) if hit["id"] not in seen
        ]
        if len(found) >= limit:
            break
    return found[:limit]
