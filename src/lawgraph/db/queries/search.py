"""Full-text and structured search query helpers.

A word of the query matches a field as ArangoSearch matched it (probed, PR #102): by its
stemmed tokens (``text``), as the start of the value as it is (``identity``), as the whole
folded value (``norm``) or as a part of 3 to 12 characters of the folded value (``ngram``).
Every word must match some field. Which fields have which matches is ``SEARCH_FIELDS`` of
``db/schema.py``; the columns are generated there. The rank within a type is ``ts_rank``
over the weighted words (``search_tsv``), not ArangoSearch's BM25: the hits are the same,
their order is held to D3.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast

from lawgraph.core.aliases import code_aliases, curated_abbreviations
from lawgraph.core.cache import _MISSING, TTLCache
from lawgraph.core.models import make_node_key
from lawgraph.core.notation import Notation, NotationParser
from lawgraph.db import GraphStore
from lawgraph.db.queries._bm25 import bm25_sql
from lawgraph.db.queries.semantic.bwb import code_alias_rows
from lawgraph.db.schema import SEARCH_FIELDS, search_column

_law_cache: TTLCache[str, Any] = TTLCache(maxsize=4, ttl=60.0)

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


# ── the condition of a search ─────────────────────────────────────────────────


def _field_condition(table: str, field: str, word: str, row: str) -> list[str]:
    """How *field* of *table* (the row *row*) matches the word in the parameter *word*,
    one condition per analyzer it was indexed with."""
    analyzers = SEARCH_FIELDS[table][field]
    parts = []
    if "text" in analyzers:
        parts.append(f"{row}.{search_column(field, 'text')} && lg_tokens(%({word})s)")
    # Each of them an index lookup: GIN on the arrays, trigrams on the strings.
    if "identity" in analyzers:
        parts.append(
            f"{row}.{search_column(field, 'prefix')}"
            f" LIKE '%%' || chr(31) || lg_like(%({word})s) || '%%'"
        )
    if "norm" in analyzers:
        parts.append(
            f"{row}.{search_column(field, 'norm')} @> ARRAY[lg_fold(%({word})s)]"
        )
    if "ngram" in analyzers:
        parts.append(
            f"(char_length(%({word})s) BETWEEN 3 AND 12"
            f" AND {row}.{search_column(field, 'ngram')} LIKE '%%' || lg_like(%({word})s) || '%%')"
        )
    return parts


def build_search_clause(
    table: str, tokens: list[str], fields: list[str], row: str = "doc"
) -> tuple[str, dict[str, Any]]:
    """A condition on *row* (a row of *table*): every token matches one of *fields*.

    Returns ``(condition, params)``; the parameters are ``_tok_0``, ``_tok_1``, … so they
    do not collide with those of the caller. A token is taken as typed (lower case, from
    ``tokenize_search_query``): its stems for the words of a field, as is for a prefix of
    its value or a part of it, folded for a whole folded value.
    """
    if not tokens:
        return "true", {}
    params: dict[str, Any] = {}
    parts: list[str] = []
    for i, token in enumerate(tokens):
        word = f"_tok_{i}"
        params[word] = token
        per_field = [c for f in fields for c in _field_condition(table, f, word, row)]
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
    """Law abbreviation (``Sr``, ``AVG``) → BWB id or CELEX number, cached for 60 s
    (``core.aliases.code_aliases``)."""
    cached = _law_cache.get("codes")
    if cached is not _MISSING:
        return cast(dict[str, str], cached)
    codes = code_aliases(code_alias_rows(store), curated_abbreviations())
    _law_cache.set("codes", codes)
    return codes


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
    """The parser of typed citations over the laws in the graph, cached for 60 s.

    Every search and every resolve shares one read of the instruments per minute instead of
    issuing one per request.
    """
    cached = _law_cache.get("parser")
    if cached is not _MISSING:
        return cast(NotationParser, cached)
    parser = NotationParser(load_code_aliases(store), _load_law_names(store))
    _law_cache.set("parser", parser)
    return parser


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
) -> Query:
    """The hits of *table* that hold every token in *fields*, the best ranked first (the
    key settles ties).

    Run it with ``store.query(..., indexes_only=True)``: its conditions and its rank read
    the large search columns, whose detoasting the planner does not count, so for a
    common word it would scan the whole table instead of using the indexes."""
    clause, clause_params = build_search_clause(table, tokens, fields)
    rank, lateral, rank_params = bm25_sql(
        store, table, clause_params, fields, _BOOSTS.get(table, {})
    )
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


def _search_articles(
    store: GraphStore,
    tokens: list[str],
    notation: Notation | None,
    limit: int,
) -> list[dict[str, Any]]:
    text = _text_query(
        store,
        "articles",
        _ARTICLE_HIT,
        tokens,
        _ARTICLE_FIELDS,
        limit,
        joins=_ARTICLE_INSTRUMENT,
    )
    if notation is None or notation.kind != "article":
        return list(store.query(*text, indexes_only=True))[:limit]

    # The law is named: the article is one key. It is not: every law with that number.
    keys = [make_node_key(a.law_id, a.number) for a in notation.articles if a.law_id]
    if keys:
        precise: Query = (
            f"""
            SELECT {_ARTICLE_HIT} FROM articles doc {_ARTICLE_INSTRUMENT}
            WHERE doc.key = ANY(%(keys)s)
            ORDER BY array_position(%(keys)s::text[], doc.key)
            LIMIT %(limit)s
            """,
            {"keys": keys, "limit": limit},
        )
    else:
        precise = (
            f"""
            SELECT {_ARTICLE_HIT} FROM articles doc {_ARTICLE_INSTRUMENT}
            WHERE doc.article_number = ANY(%(numbers)s)
            ORDER BY doc.bwb_id NULLS FIRST, doc.key
            LIMIT %(limit)s
            """,
            {"numbers": [a.number for a in notation.articles], "limit": limit},
        )
    return _two_phase_search(store, precise, text, limit)


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
    store: GraphStore, q: str, tokens: list[str], limit: int
) -> list[dict[str, Any]]:
    """Instruments whose alias or short title is the whole query first (``Boek 6 BW``,
    ``BW``), then those that hold its words."""
    precise: Query = (
        f"""
        SELECT {_INSTRUMENT_HIT} FROM instruments doc
        WHERE doc.{search_column("aliases", "norm")} @> ARRAY[lg_fold(%(name)s)]
           OR doc.{search_column("short_title", "norm")} @> ARRAY[lg_fold(%(name)s)]
        ORDER BY doc.citation_title NULLS FIRST, doc.key
        LIMIT %(limit)s
        """,
        {"name": _folded(q), "limit": limit},
    )
    text = _text_query(
        store, "instruments", _INSTRUMENT_HIT, tokens, _INSTRUMENT_FIELDS, limit
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
) -> list[dict[str, Any]]:
    text = _text_query(
        store, "judgments", _JUDGMENT_HIT, tokens, _JUDGMENT_FIELDS, limit
    )
    if notation is not None and notation.kind == "ecli":
        ecli: Query = (
            f"""
            SELECT {_ECLI_HIT} FROM judgments doc
            WHERE doc.ecli = %(ecli)s
            ORDER BY doc.key
            LIMIT %(limit)s
            """,
            {"ecli": notation.identifier, "limit": limit},
        )
        return _two_phase_search(store, ecli, text, limit)

    # The query may be the name of a judgment ("Urgenda", "Lindenbaum/Cohen"): those first,
    # the latest decision first (of one case: the highest court), a translation after the
    # judgment it translates.
    name: Query = (
        f"""
        SELECT {_JUDGMENT_HIT} FROM judgments doc
        WHERE doc.{search_column("names", "norm")} @> ARRAY[lg_fold(%(name)s)]
        ORDER BY doc.date_eff DESC NULLS LAST,
                 coalesce(json_typeof(doc.props -> 'translation_of'), 'null') <> 'null',
                 doc.key
        LIMIT %(limit)s
        """,
        {"name": q.strip(), "limit": limit},
    )
    return _two_phase_search(store, name, text, limit)


# ── dossiers, committees, documents ──────────────────────────────────────────

_KIND = "AND lower(doc.props ->> 'kind') = ANY(%(kind_filter)s)"
# The chamber of a document from its labels, as ``/api/documents`` reads it
# (``queries/documents._CHAMBER_OF``): null for a Staatsblad or Staatscourant publication.
_CHAMBER = "CASE WHEN 'EK' = ANY(doc.labels) THEN 'EK' WHEN 'TK' = ANY(doc.labels) THEN 'TK' END"


def _search_dossiers(
    store: GraphStore,
    tokens: list[str],
    kinds: list[str] | None,
    limit: int,
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
                'outcome', doc.props -> 'outcome'
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
        where=_KIND if kinds else "",
        params={"kind_filter": [k.lower() for k in kinds or []]},
    )
    return list(store.query(*query, indexes_only=True))


def _search_committees(
    store: GraphStore, tokens: list[str], limit: int
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
        store, "committees", hit, tokens, ["name", "abbreviation"], limit
    )
    return list(store.query(*query, indexes_only=True))


def _search_documents(
    store: GraphStore,
    tokens: list[str],
    kinds: list[str] | None,
    limit: int,
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
                'date', doc.props -> 'date',
                'chamber', {_CHAMBER}
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
        where=_KIND if kinds else "",
        params={"kind_filter": [k.lower() for k in kinds or []]},
    )
    return list(store.query(*query, indexes_only=True))


# ── members and factions: every word in their names ─────────────────────────


def _all_words(tokens: list[str]) -> tuple[str, dict[str, Any]]:
    """Every token is a part of the names (``search_names``, lower case): a trigram lookup
    each."""
    params = {f"_word_{i}": token for i, token in enumerate(tokens)}
    condition = " AND ".join(
        f"doc.search_names LIKE '%%' || lg_like(%({name})s) || '%%'" for name in params
    )
    return condition, params


def _search_members(
    store: GraphStore, tokens: list[str], limit: int
) -> list[dict[str, Any]]:
    condition, params = _all_words(tokens)
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
    condition, params = _all_words(tokens)
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


def _folded(value: Any) -> str:
    return " ".join(str(value).lower().split()) if value else ""


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
) -> dict[str, list[dict[str, Any]]]:
    """Full-text search across requested entity types.

    Returns a dict keyed by type name with a list of hit dicts each containing
    {id, key, collection, type, display_name, snippet, extra, score}, best score first.

    Every token must appear — AND semantics: in the searched fields of the indexed types,
    in the names of members and factions.
    """
    tokens = tokenize_search_query(q)
    if not tokens:
        return {t: [] for t in types}

    parser = (
        load_notation_parser(store) if {"articles", "judgments"} & set(types) else None
    )
    notation = parser.parse(q) if parser else None

    searches: dict[str, Callable[[], list[dict[str, Any]]]] = {
        "articles": lambda: _search_articles(store, tokens, notation, limit),
        "instruments": lambda: _search_instruments(store, q, tokens, limit),
        "judgments": lambda: _search_judgments(store, tokens, notation, limit, q),
        "dossiers": lambda: _search_dossiers(store, tokens, kinds, limit),
        "committees": lambda: _search_committees(store, tokens, limit),
        "members": lambda: _search_members(store, tokens, limit),
        "factions": lambda: _search_factions(store, tokens, limit),
        "documents": lambda: _search_documents(store, tokens, kinds, limit),
    }
    wanted = [t for t in types if t in searches]
    # The types are searched side by side, each on a connection of its own: the answer
    # takes as long as the slowest type, not as long as all of them.
    found = _SEARCHES.map(lambda t: searches[t](), wanted)
    return {t: rank_hits(q, hits) for t, hits in zip(wanted, found, strict=True)}


_SEARCHES = ThreadPoolExecutor(max_workers=4, thread_name_prefix="search")
