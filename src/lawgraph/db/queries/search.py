"""Full-text and structured search query helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_FACTIONS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    COLLECTION_MEMBERS,
    TEXT_ANALYZER,
)
from lawgraph.core.cache import _MISSING, TTLCache
from lawgraph.core.models import make_node_key
from lawgraph.core.notation import Notation, NotationParser
from lawgraph.db import ArangoStore

_law_cache: TTLCache[str, Any] = TTLCache(maxsize=4, ttl=60.0)

# The score of a hit is the tier of the best way it matches the query. Ties keep the order
# of the database (BM25 within a type).
SCORE_IDENTIFIER = 1.0  # the query is the hit's key or one of its identifiers
SCORE_TITLE = 0.75  # the query is the whole of its name
SCORE_PREFIX = 0.5  # its name starts with the query
SCORE_CONTAINS = 0.25  # every word of the query is in its name
SCORE_WORDS = 0.1  # it matched on stems or text only

# The part of an article hit that names its parent instrument, looked up per hit after the
# LIMIT: an index lookup on the instrument of each of the (at most ``limit``) hits, inside
# the one query. Articles of EU acts carry a CELEX id instead of a BWB id.
_ARTICLE_HIT = f"""
    // the tail of a query over `doc`: the article with its instrument
    LET instrument = FIRST(
        FOR i IN {COLLECTION_INSTRUMENTS}
            FILTER doc.props.bwb_id != null AND i.props.bwb_id == doc.props.bwb_id
            LIMIT 1
            RETURN {{
                title: i.props.title,
                citation_title: i.props.citation_title,
                short_title: i.props.short_title
            }}
    ) OR FIRST(
        FOR i IN {COLLECTION_INSTRUMENTS}
            FILTER doc.props.celex != null AND i.props.celex == doc.props.celex
            LIMIT 1
            RETURN {{
                title: i.props.title,
                citation_title: i.props.citation_title,
                short_title: i.props.short_title
            }}
    )
    RETURN {{
        id: doc._id, key: doc._key,
        collection: 'articles', type: doc.type,
        display_name: doc.props.display_name,
        snippet: LEFT(doc.props.text, 200),
        extra: {{
            bwb_id: doc.props.bwb_id,
            celex: doc.props.celex,
            article_number: doc.props.article_number,
            heading: doc.props.heading,
            division_titles: doc.props.breadcrumb[* FILTER CURRENT.title != null RETURN CURRENT.title],
            instrument_title: NOT_NULL(instrument.citation_title, instrument.title),
            citation_title: instrument.citation_title,
            short_title: instrument.short_title
        }}
    }}
"""


# Follows ``SEARCH <clause>``. The clause is an AND of one OR per word; the optimizer turns it
# into an OR of ANDs, which for five words over seven fields is millions of terms, and gives
# up with "ArangoSearch noncompliant expression". Left as written it runs as it reads.
SEARCH_OPTIONS = 'OPTIONS { conditionOptimization: "none" }'


def build_search_clause(
    tokens: list[str],
    fields: list[str],
    boosts: Mapping[str, float] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Build an ArangoSearch clause: every token must appear in any of *fields*.

    Returns ``(clause, bind_vars)``. The clause is meant to be wrapped in
    ``SEARCH ANALYZER(<clause>, TEXT_ANALYZER)``. Bind vars are namespaced as
    ``_tok_0``, ``_tok_1``, … so they don't collide with caller bindings.

    Each token is fed through ``TOKENS(@val, TEXT_ANALYZER)`` at query time so the
    stemmer is applied symmetrically on both sides. Without this, bind values
    are compared as literals against the (stemmed) indexed tokens — e.g. a
    search for "Strafvordering" misses because the index stores ``strafvord``
    but the literal value never reaches the stemmer.

    Each token also gets a ``STARTS_WITH`` fallback so prefix matches keep
    working when the stemmer doesn't help (e.g. abbreviations and codes like
    ``BWBR``). AQL doesn't allow dynamic FOR loops inside SEARCH, so we
    materialise the AND-of-OR expression at Python side.

    *boosts* weighs a field in the BM25 score (``BOOST``): a heading or an alias that holds
    the words ranks above a long text that does, before the ``LIMIT`` cuts.
    A field may be a path into an array of objects (``breadcrumb.title``).
    """
    if not tokens:
        return "true", {}
    bind_vars: dict[str, Any] = {}
    parts: list[str] = []
    for i, t in enumerate(tokens):
        bind_vars[f"_tok_{i}"] = t
        per_field: list[str] = []
        for f in fields:
            boost = (boosts or {}).get(f)
            field_parts: list[str] = []
            # 1) Stem-aware token match via TEXT_ANALYZER — analyzer applied to
            #    both indexed field and bind value.
            field_parts.append(
                f"ANALYZER(doc.props.{f} IN TOKENS(@_tok_{i}, '{TEXT_ANALYZER}'), "
                f"'{TEXT_ANALYZER}')"
            )
            # 2) Case-sensitive prefix on identity-indexed fields.
            field_parts.append(
                f"ANALYZER(STARTS_WITH(doc.props.{f}, @_tok_{i}), 'identity')"
            )
            # 3) Case-insensitive identifier match via lawgraph_norm —
            #    bwb_id/ecli/number typed in any case.
            field_parts.append(f"ANALYZER(doc.props.{f} == @_tok_{i}, 'lawgraph_norm')")
            # 4) Substring match via 3..12-gram analyzer for compound words
            #    (Vordering → Strafvordering, etc.). Using `==` under the
            #    pipeline ngram analyzer reduces to "any indexed ngram of
            #    the field overlaps any query ngram" — which behaves as a
            #    substring probe when the analyzer covers ngrams up to
            #    query length. NGRAM_MATCH would be canonical but doesn't
            #    use the inverted index for pipeline analyzers in this
            #    Arango version, so it returns 0 hits from the view.
            field_parts.append(
                f"ANALYZER(doc.props.{f} == @_tok_{i}, 'lawgraph_ngram_v2')"
            )
            if boost:
                field_parts = [f"BOOST({part}, {boost})" for part in field_parts]
            per_field.extend(field_parts)
        parts.append("(" + " OR ".join(per_field) + ")")
    return " AND ".join(parts), bind_vars


def tokenize_search_query(q: str) -> list[str]:
    """Split a free-text query into lowercase tokens for AND-matching.

    Whitespace is the only separator; punctuation is preserved inside tokens
    so identifiers like ``BWBR0001903`` or ``ECLI:NL:HR:2023:1`` remain intact.
    Tokens of length 1 are dropped to avoid pathological scans.
    """
    return [t for t in q.strip().lower().split() if len(t) > 1]


# ── Intent-aware search parser ────────────────────────────────────────────────


def load_code_aliases(store: ArangoStore) -> dict[str, str]:
    """Law abbreviation (``short_title``, e.g. ``Sr``) → bwb_id, cached for 60 s."""
    cached = _law_cache.get("codes")
    if cached is not _MISSING:
        return cast(dict[str, str], cached)

    aql = f"""
    FOR i IN {COLLECTION_INSTRUMENTS}
        FILTER i.props.bwb_id != null AND i.props.short_title != null
        RETURN [i.props.short_title, i.props.bwb_id]
    """
    codes = dict(store.query(aql))
    _law_cache.set("codes", codes)
    return codes


def _load_law_names(store: ArangoStore) -> dict[str, list[str]]:
    """Lower-case law name → the BWB or CELEX ids that carry it (a name may be shared)."""
    aql = f"""
    FOR i IN {COLLECTION_INSTRUMENTS}
        LET law_id = NOT_NULL(i.props.bwb_id, i.props.celex)
        FILTER law_id != null
        RETURN {{
            law_id: law_id,
            names: [i.props.short_title, i.props.citation_title, i.props.title]
        }}
    """
    names: dict[str, list[str]] = {}
    for row in store.query(aql):
        for name in row["names"]:
            if isinstance(name, str) and name.strip():
                known = names.setdefault(name.strip().lower(), [])
                if row["law_id"] not in known:
                    known.append(row["law_id"])
    return names


def load_notation_parser(store: ArangoStore) -> NotationParser:
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
    store: ArangoStore,
    precise_aql: str,
    precise_vars: dict[str, Any],
    text_aql: str,
    text_vars: dict[str, Any],
    limit: int,
    precise_score: float | None = SCORE_IDENTIFIER,
) -> list[dict[str, Any]]:
    """Run a precise lookup then a full-text fallback, deduplicating by id.

    What the precise lookup finds is what the query names, so it scores as an identifier
    unless *precise_score* is None: then ``score_hit`` scores it like any hit.
    """
    seen: set[str] = set()
    results: list[dict[str, Any]] = []
    for row in store.query(precise_aql, precise_vars):
        rid = row.get("id")
        if rid and rid not in seen:
            seen.add(rid)
            results.append(
                row if precise_score is None else {**row, "score": precise_score}
            )
    if len(results) < limit:
        for row in store.query(text_aql, text_vars):
            if row.get("id") not in seen:
                seen.add(row["id"])
                results.append(row)
    return results[:limit]


# A word in the heading of an article weighs most, one in the title of a division it stands
# in (titel, afdeling) more than one in its text.
_ARTICLE_BOOSTS = {"heading": 4.0, "display_name": 2.0, "breadcrumb.title": 1.5}
# A word in a name a law is cited by weighs more than one in its long title.
_INSTRUMENT_BOOSTS = {"aliases": 3.0, "short_title": 3.0, "citation_title": 2.0}

# The instrument hit, from ``doc``.
_INSTRUMENT_HIT = """
    RETURN {
        id: doc._id, key: doc._key,
        collection: 'instruments', type: doc.type,
        display_name: (
            doc.props.citation_title != null ? doc.props.citation_title :
            (doc.props.display_name != null ? doc.props.display_name : doc.props.title)
        ),
        snippet: LEFT(doc.props.title, 200),
        extra: {
            bwb_id: doc.props.bwb_id,
            citation_title: doc.props.citation_title,
            short_title: doc.props.short_title,
            aliases: doc.props.aliases
        }
    }
"""


def _search_articles(
    store: ArangoStore,
    tokens: list[str],
    notation: Notation | None,
    limit: int,
) -> list[dict[str, Any]]:
    clause, tok_bind = build_search_clause(
        tokens,
        [
            "display_name",
            "heading",
            "breadcrumb.title",
            "text",
            "article_number",
            "bwb_id",
        ],
        _ARTICLE_BOOSTS,
    )
    text_aql = f"""
    FOR doc IN search_articles
        SEARCH {clause} {SEARCH_OPTIONS}
        SORT BM25(doc) DESC
        LIMIT @limit
        {_ARTICLE_HIT}
    """
    text_vars = {**tok_bind, "limit": limit}

    if notation is None or notation.kind != "article":
        return list(store.query(text_aql, text_vars))[:limit]

    # The law is named: the article is one key. It is not: every law with that number.
    keys = [make_node_key(a.law_id, a.number) for a in notation.articles if a.law_id]
    if keys:
        precise_aql = f"""
        FOR doc IN {COLLECTION_ARTICLES}
            FILTER doc._key IN @keys
            LIMIT @limit
            {_ARTICLE_HIT}
        """
        precise_vars: dict[str, Any] = {"keys": keys, "limit": limit}
    else:
        precise_aql = f"""
        FOR doc IN {COLLECTION_ARTICLES}
            FILTER doc.props.article_number IN @numbers
            SORT doc.props.bwb_id ASC
            LIMIT @limit
            {_ARTICLE_HIT}
        """
        precise_vars = {
            "numbers": [a.number for a in notation.articles],
            "limit": limit,
        }
    return _two_phase_search(
        store, precise_aql, precise_vars, text_aql, text_vars, limit
    )


def _search_instruments(
    store: ArangoStore, q: str, tokens: list[str], limit: int
) -> list[dict[str, Any]]:
    """Instruments whose alias or short title is the whole query first (``Boek 6 BW``,
    ``BW``), then those that hold its words."""
    clause, tok_bind = build_search_clause(
        tokens,
        [
            "title",
            "citation_title",
            "official_title",
            "display_name",
            "short_title",
            "aliases",
            "bwb_id",
        ],
        _INSTRUMENT_BOOSTS,
    )
    precise_aql = f"""
    FOR doc IN search_instruments
        SEARCH ANALYZER(doc.props.aliases == @name OR doc.props.short_title == @name,
                        'lawgraph_norm')
        SORT doc.props.citation_title ASC
        LIMIT @limit
        {_INSTRUMENT_HIT}
    """
    text_aql = f"""
    FOR doc IN search_instruments
        SEARCH {clause} {SEARCH_OPTIONS}
        SORT BM25(doc) DESC
        LIMIT @limit
        {_INSTRUMENT_HIT}
    """
    return _two_phase_search(
        store,
        precise_aql,
        {"name": _folded(q), "limit": limit},
        text_aql,
        {**tok_bind, "limit": limit},
        limit,
        precise_score=None,
    )


def _search_judgments(
    store: ArangoStore,
    tokens: list[str],
    notation: Notation | None,
    limit: int,
) -> list[dict[str, Any]]:
    clause, tok_bind = build_search_clause(
        tokens, ["display_name", "summary", "ecli", "appno"]
    )
    text_aql = f"""
    FOR doc IN search_judgments
        SEARCH {clause} {SEARCH_OPTIONS}
        SORT BM25(doc) DESC
        LIMIT @limit
        RETURN {{
            id: doc._id, key: doc._key,
            collection: 'judgments', type: doc.type,
            display_name: doc.props.display_name,
            snippet: LEFT(doc.props.summary, 200),
            extra: {{ ecli: doc.props.ecli, appno: doc.props.appno }}
        }}
    """

    if notation is not None and notation.kind == "ecli":
        ecli_aql = f"""
        FOR doc IN {COLLECTION_JUDGMENTS}
            FILTER doc.props.ecli == @ecli
            LIMIT @limit
            RETURN {{
                id: doc._id, key: doc._key,
                collection: 'judgments', type: doc.type,
                display_name: doc.props.display_name,
                snippet: LEFT(doc.props.summary, 200),
                extra: {{ ecli: doc.props.ecli }}
            }}
        """
        return _two_phase_search(
            store,
            ecli_aql,
            {"ecli": notation.identifier, "limit": limit},
            text_aql,
            {**tok_bind, "limit": limit},
            limit,
        )

    return list(store.query(text_aql, {**tok_bind, "limit": limit}))[:limit]


def _search_dossiers(
    store: ArangoStore,
    tokens: list[str],
    kinds: list[str] | None,
    limit: int,
) -> list[dict[str, Any]]:
    clause, tok_bind = build_search_clause(tokens, ["title", "display_name", "number"])
    bind_vars: dict[str, Any] = {**tok_bind, "limit": limit}
    kind_clause = ""
    if kinds:
        kind_clause = "FILTER LOWER(doc.props.current_stage) IN @kind_filter"
        bind_vars["kind_filter"] = [k.lower() for k in kinds]
    aql = f"""
    FOR doc IN search_dossiers
        SEARCH {clause} {SEARCH_OPTIONS}
        {kind_clause}
        SORT BM25(doc) DESC
        LIMIT @limit
        RETURN {{
            id: doc._id, key: doc._key,
            collection: 'dossiers', type: doc.type,
            display_name: (doc.props.title != null ? doc.props.title : doc.props.display_name),
            snippet: doc.props.label,
            extra: {{
                number: doc.props.label,
                current_stage: doc.props.current_stage,
                closed: doc.props.closed,
                outcome: doc.props.outcome
            }}
        }}
    """
    return list(store.query(aql, bind_vars))


def _search_committees(
    store: ArangoStore, tokens: list[str], limit: int
) -> list[dict[str, Any]]:
    clause, tok_bind = build_search_clause(tokens, ["name", "abbreviation"])
    aql = f"""
    FOR doc IN search_committees
        SEARCH {clause} {SEARCH_OPTIONS}
        SORT BM25(doc) DESC
        LIMIT @limit
        RETURN {{
            id: doc._id, key: doc._key,
            collection: 'committees', type: doc.type,
            display_name: doc.props.name,
            snippet: doc.props.abbreviation,
            extra: {{ slug: doc.props.slug, abbreviation: doc.props.abbreviation }}
        }}
    """
    return list(store.query(aql, {**tok_bind, "limit": limit}))


def _search_members(
    store: ArangoStore, tokens: list[str], limit: int
) -> list[dict[str, Any]]:
    aql = f"""
    FOR doc IN {COLLECTION_MEMBERS}
        LET membership_labels = (
            FOR m IN (doc.props.faction_memberships OR [])
                RETURN CONCAT_SEPARATOR(" ",
                    m.abbreviation != null ? m.abbreviation : "",
                    m.name != null ? m.name : "",
                    CONCAT_SEPARATOR(" ", m.aliases OR [])
                )
        )
        LET haystack = LOWER(CONCAT_SEPARATOR(" ",
            doc.props.name OR "",
            doc.props.party OR "",
            CONCAT_SEPARATOR(" ", membership_labels)
        ))
        FILTER LENGTH(FOR t IN @tokens FILTER NOT CONTAINS(haystack, t) LIMIT 1 RETURN 1) == 0
        SORT doc.props.active DESC, doc.props.name ASC
        LIMIT @limit
        RETURN {{
            id: doc._id, key: doc._key,
            collection: 'members', type: doc.type,
            display_name: doc.props.name,
            snippet: doc.props.party,
            extra: {{ party: doc.props.party, active: doc.props.active }}
        }}
    """
    return list(store.query(aql, {"tokens": tokens, "limit": limit}))


def _search_factions(
    store: ArangoStore, tokens: list[str], limit: int
) -> list[dict[str, Any]]:
    aql = f"""
    FOR doc IN {COLLECTION_FACTIONS}
        LET haystack = LOWER(CONCAT_SEPARATOR(" ",
            doc.props.name OR "",
            doc.props.abbreviation OR "",
            CONCAT_SEPARATOR(" ", doc.props.aliases OR [])
        ))
        FILTER LENGTH(FOR t IN @tokens FILTER NOT CONTAINS(haystack, t) LIMIT 1 RETURN 1) == 0
        SORT doc.props.active DESC,
             (doc.props.seats != null ? doc.props.seats : 0) DESC,
             doc.props.name ASC
        LIMIT @limit
        RETURN {{
            id: doc._id, key: doc._key,
            collection: 'factions', type: doc.type,
            display_name: doc.props.name,
            snippet: doc.props.abbreviation,
            extra: {{
                abbreviation: doc.props.abbreviation,
                seats: doc.props.seats,
                active: doc.props.active
            }}
        }}
    """
    return list(store.query(aql, {"tokens": tokens, "limit": limit}))


def _search_documents(
    store: ArangoStore,
    tokens: list[str],
    kinds: list[str] | None,
    limit: int,
) -> list[dict[str, Any]]:
    clause, tok_bind = build_search_clause(
        tokens, ["display_name", "title", "external_id"]
    )
    bind_vars: dict[str, Any] = {**tok_bind, "limit": limit}
    kind_clause = ""
    if kinds:
        kind_clause = "FILTER LOWER(doc.props.kind) IN @kind_filter"
        bind_vars["kind_filter"] = [k.lower() for k in kinds]
    # Hydrated PDF text isn't indexed in the view (~500 KB rows are too
    # bulky for sub-200-ms search); identifier and title fields cover
    # the UI use cases. A dedicated full-text endpoint can opt-in.
    aql = f"""
    FOR doc IN search_documents
        SEARCH {clause} {SEARCH_OPTIONS}
        {kind_clause}
        SORT BM25(doc) DESC
        LIMIT @limit
        RETURN {{
            id: doc._id, key: doc._key,
            collection: 'documents', type: doc.type,
            display_name: (doc.props.title != null ? doc.props.title : doc.props.display_name),
            snippet: doc.props.kind,
            extra: {{
                kind: doc.props.kind,
                external_id: doc.props.external_id,
                dossier_number: FIRST(doc.props.dossier_numbers)
            }}
        }}
    """
    return list(store.query(aql, bind_vars))


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
    store: ArangoStore,
    *,
    q: str,
    types: list[str],
    kinds: list[str] | None = None,
    limit: int = 20,
) -> dict[str, list[dict[str, Any]]]:
    """Full-text search across requested entity types.

    Returns a dict keyed by type name with a list of hit dicts each containing
    {id, key, collection, type, display_name, snippet, extra, score}, best score first.

    Uses ArangoSearch views for indexed types and CONTAINS for small
    collections (members, factions). Every token must appear — AND semantics.
    """
    tokens = tokenize_search_query(q)
    if not tokens:
        return {t: [] for t in types}

    parser = (
        load_notation_parser(store) if {"articles", "judgments"} & set(types) else None
    )
    notation = parser.parse(q) if parser else None

    results: dict[str, list[dict[str, Any]]] = {}
    for t in types:
        if t == "articles":
            results[t] = _search_articles(store, tokens, notation, limit)
        elif t == "instruments":
            results[t] = _search_instruments(store, q, tokens, limit)
        elif t == "judgments":
            results[t] = _search_judgments(store, tokens, notation, limit)
        elif t == "dossiers":
            results[t] = _search_dossiers(store, tokens, kinds, limit)
        elif t == "committees":
            results[t] = _search_committees(store, tokens, limit)
        elif t == "members":
            results[t] = _search_members(store, tokens, limit)
        elif t == "factions":
            results[t] = _search_factions(store, tokens, limit)
        elif t == "documents":
            results[t] = _search_documents(store, tokens, kinds, limit)
    return {t: rank_hits(q, hits) for t, hits in results.items()}
