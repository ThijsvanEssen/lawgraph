"""Full-text and structured search query helpers."""

from __future__ import annotations

import re
from typing import Any

from lawgraph.api.cache import TTLCache
from lawgraph.db import ArangoStore

_alias_map_cache: TTLCache[str, dict[str, str]] = TTLCache(maxsize=4, ttl=60.0)

# Shared LET block that pre-loads bwb→instrument metadata once per query.
# Used by article search branches to annotate hits with parent law info.
_INSTRUMENT_ENRICH_AQL = """
LET bwb_to_inst = MERGE(
    FOR i IN instruments
        FILTER i.props.bwb_id != null
        RETURN {
            [i.props.bwb_id]: {
                citation_title: i.props.citation_title,
                short_title: i.props.short_title,
                title: i.props.title
            }
        }
)
"""

_ARTICLE_RETURN = """{
    bwb_id: doc.props.bwb_id,
    article_number: doc.props.article_number,
    citation_title: bwb_to_inst[doc.props.bwb_id].citation_title,
    short_title: bwb_to_inst[doc.props.bwb_id].short_title
}"""


def build_search_clause(
    tokens: list[str], fields: list[str]
) -> tuple[str, dict[str, Any]]:
    """Build an ArangoSearch clause: every token must appear in any of *fields*.

    Returns ``(clause, bind_vars)``. The clause is meant to be wrapped in
    ``SEARCH ANALYZER(<clause>, "text_en")``. Bind vars are namespaced as
    ``_tok_0``, ``_tok_1``, … so they don't collide with caller bindings.

    Each token is fed through ``TOKENS(@val, 'text_en')`` at query time so the
    stemmer is applied symmetrically on both sides. Without this, bind values
    are compared as literals against the (stemmed) indexed tokens — e.g. a
    search for "Strafvordering" misses because the index stores ``strafvord``
    but the literal value never reaches the stemmer.

    Each token also gets a ``STARTS_WITH`` fallback so prefix matches keep
    working when the stemmer doesn't help (e.g. abbreviations and codes like
    ``BWBR``). AQL doesn't allow dynamic FOR loops inside SEARCH, so we
    materialise the AND-of-OR expression at Python side.
    """
    if not tokens:
        return "true", {}
    bind_vars: dict[str, Any] = {}
    parts: list[str] = []
    for i, t in enumerate(tokens):
        bind_vars[f"_tok_{i}"] = t
        per_field: list[str] = []
        for f in fields:
            # 1) Stem-aware token match via text_en — analyzer applied to
            #    both indexed field and bind value.
            per_field.append(
                f"ANALYZER(doc.props.{f} IN TOKENS(@_tok_{i}, 'text_en'), 'text_en')"
            )
            # 2) Case-sensitive prefix on identity-indexed fields.
            per_field.append(
                f"ANALYZER(STARTS_WITH(doc.props.{f}, @_tok_{i}), 'identity')"
            )
            # 3) Case-insensitive identifier match via lawgraph_norm —
            #    bwb_id/ecli/kamerstuknummer typed in any case.
            per_field.append(f"ANALYZER(doc.props.{f} == @_tok_{i}, 'lawgraph_norm')")
            # 4) Substring match via 3..12-gram analyzer for compound words
            #    (Vordering → Strafvordering, etc.). Using `==` under the
            #    pipeline ngram analyzer reduces to "any indexed ngram of
            #    the field overlaps any query ngram" — which behaves as a
            #    substring probe when the analyzer covers ngrams up to
            #    query length. NGRAM_MATCH would be canonical but doesn't
            #    use the inverted index for pipeline analyzers in this
            #    Arango version, so it returns 0 hits from the view.
            per_field.append(
                f"ANALYZER(doc.props.{f} == @_tok_{i}, 'lawgraph_ngram_v2')"
            )
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

_ARTICLE_PREFIX_RE = re.compile(
    r"^(?:art\.?|artikel)\s+(\d+[a-z]*)\b\s*(.*)$",
    re.IGNORECASE,
)
_ARTICLE_SUFFIX_RE = re.compile(
    r"^(.+?)\s+(?:art\.?|artikel)?\s*(\d+[a-z]*)$",
    re.IGNORECASE,
)
_ECLI_RE = re.compile(r"^ECLI:[A-Z]{2}:[A-Z0-9]+:\d{4}:[A-Z0-9._-]+$", re.IGNORECASE)


def load_instrument_alias_map(store: ArangoStore) -> dict[str, str]:
    """Return a lowercased alias → bwb_id map for known instruments.

    Aliases come from each instrument's ``short_title``, ``citation_title``,
    and ``title`` props. Result is cached for 60 s so repeated searches within
    the same minute share one round-trip instead of issuing one per request.
    """
    cached = _alias_map_cache.get("map")
    if cached is not None:
        return cached

    aql = """
    FOR i IN instruments
        FILTER i.props.bwb_id != null
        RETURN {
            bwb_id: i.props.bwb_id,
            short: i.props.short_title,
            citation: i.props.citation_title,
            title: i.props.title
        }
    """
    alias_map: dict[str, str] = {}
    for row in store.query(aql):
        bwb = str(row.get("bwb_id") or "").strip()
        if not bwb:
            continue
        for key in ("short", "citation", "title"):
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                alias_map[value.strip().lower()] = bwb
    _alias_map_cache.set("map", alias_map)
    return alias_map


def parse_search_query(q: str, alias_map: dict[str, str]) -> dict[str, Any]:
    """Inspect *q* for known reference patterns.

    Returns one of:
      * ``{"kind": "ecli", "ecli": "..."}`` — full ECLI string.
      * ``{"kind": "article", "bwb_id": Optional[str], "article_number": str}``
      * ``{"kind": "text"}`` — fall through to AND-token search.

    The parser is best-effort. Anything not recognised falls back to text.
    """
    stripped = q.strip()
    if not stripped:
        return {"kind": "text"}

    if _ECLI_RE.match(stripped):
        return {"kind": "ecli", "ecli": stripped.upper()}

    def _resolve_law(raw: str) -> str | None:
        cleaned = raw.strip().rstrip(",.;:").lower()
        if not cleaned:
            return None
        if cleaned in alias_map:
            return alias_map[cleaned]
        # Suffix match: "het wetboek van strafrecht" → "wetboek van strafrecht"
        for alias, bwb in alias_map.items():
            if cleaned.endswith(alias) or cleaned.startswith(alias):
                return bwb
        return None

    # "Art. 1 Grondwet" / "artikel 287 Sr" / "art 1"
    m = _ARTICLE_PREFIX_RE.match(stripped)
    if m:
        article_number = m.group(1).lower()
        rest = m.group(2).strip()
        bwb_id = _resolve_law(rest) if rest else None
        return {
            "kind": "article",
            "bwb_id": bwb_id,
            "article_number": article_number,
        }

    # "Sr 287" / "Wetboek van Strafrecht art 1" / "Grondwet 1"
    m = _ARTICLE_SUFFIX_RE.match(stripped)
    if m:
        prefix = m.group(1).strip()
        article_number = m.group(2).lower()
        # Strip a trailing "art"/"artikel" from the prefix if present.
        prefix = re.sub(r"\s*(?:art\.?|artikel)\s*$", "", prefix, flags=re.IGNORECASE)
        bwb_id = _resolve_law(prefix)
        if bwb_id is not None:
            return {
                "kind": "article",
                "bwb_id": bwb_id,
                "article_number": article_number,
            }

    return {"kind": "text"}


# ── Per-type search helpers ───────────────────────────────────────────────────


def _two_phase_search(
    store: ArangoStore,
    precise_aql: str,
    precise_vars: dict[str, Any],
    text_aql: str,
    text_vars: dict[str, Any],
    limit: int,
) -> list[dict[str, Any]]:
    """Run a precise lookup then a full-text fallback, deduplicating by id."""
    seen: set[str] = set()
    results: list[dict[str, Any]] = []
    for row in store.query(precise_aql, precise_vars):
        rid = row.get("id")
        if rid and rid not in seen:
            seen.add(rid)
            results.append(row)
    if len(results) < limit:
        for row in store.query(text_aql, text_vars):
            if row.get("id") not in seen:
                seen.add(row["id"])
                results.append(row)
    return results[:limit]


def _search_articles(
    store: ArangoStore,
    tokens: list[str],
    intent: dict[str, Any],
    limit: int,
) -> list[dict[str, Any]]:
    clause, tok_bind = build_search_clause(
        tokens, ["display_name", "text", "article_number", "bwb_id"]
    )
    text_aql = f"""
    {_INSTRUMENT_ENRICH_AQL}
    FOR doc IN search_articles
        SEARCH {clause}
        SORT BM25(doc) DESC
        LIMIT @limit
        RETURN {{
            id: doc._id, key: doc._key,
            collection: 'instrument_articles', type: doc.type,
            display_name: doc.props.display_name,
            snippet: LEFT(doc.props.text, 200),
            extra: {_ARTICLE_RETURN}
        }}
    """

    if intent.get("kind") == "article" and intent.get("article_number"):
        precise_aql = f"""
        {_INSTRUMENT_ENRICH_AQL}
        FOR doc IN instrument_articles
            FILTER doc.props.article_number == @article_number
            FILTER @bwb_id == null OR doc.props.bwb_id == @bwb_id
            SORT doc.props.bwb_id ASC
            LIMIT @limit
            RETURN {{
                id: doc._id, key: doc._key,
                collection: 'instrument_articles', type: doc.type,
                display_name: doc.props.display_name,
                snippet: LEFT(doc.props.text, 200),
                extra: {_ARTICLE_RETURN}
            }}
        """
        precise_vars: dict[str, Any] = {
            "article_number": intent["article_number"],
            "bwb_id": intent.get("bwb_id"),
            "limit": limit,
        }
        results = _two_phase_search(
            store,
            precise_aql,
            precise_vars,
            text_aql,
            {**tok_bind, "limit": limit},
            limit,
        )
        # Skip full-text scan when intent already matched — precise lookup is always better.
        if intent.get("kind") == "article":
            return results
        return results

    return list(store.query(text_aql, {**tok_bind, "limit": limit}))[:limit]


def _search_instruments(
    store: ArangoStore, tokens: list[str], limit: int
) -> list[dict[str, Any]]:
    clause, tok_bind = build_search_clause(
        tokens, ["title", "citation_title", "official_title", "display_name", "short_title", "bwb_id"]
    )
    aql = f"""
    FOR doc IN search_instruments
        SEARCH {clause}
        SORT BM25(doc) DESC
        LIMIT @limit
        RETURN {{
            id: doc._id, key: doc._key,
            collection: 'instruments', type: doc.type,
            display_name: (
                doc.props.citation_title != null ? doc.props.citation_title :
                (doc.props.display_name != null ? doc.props.display_name : doc.props.title)
            ),
            snippet: LEFT(doc.props.title, 200),
            extra: {{ bwb_id: doc.props.bwb_id, citation_title: doc.props.citation_title }}
        }}
    """
    return list(store.query(aql, {**tok_bind, "limit": limit}))


def _search_judgments(
    store: ArangoStore,
    tokens: list[str],
    intent: dict[str, Any],
    limit: int,
) -> list[dict[str, Any]]:
    clause, tok_bind = build_search_clause(tokens, ["display_name", "summary", "ecli", "appno"])
    text_aql = f"""
    FOR doc IN search_judgments
        SEARCH {clause}
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

    if intent.get("kind") == "ecli" and intent.get("ecli"):
        ecli_aql = """
        FOR doc IN judgments
            FILTER doc.props.ecli == @ecli
            LIMIT @limit
            RETURN {
                id: doc._id, key: doc._key,
                collection: 'judgments', type: doc.type,
                display_name: doc.props.display_name,
                snippet: LEFT(doc.props.summary, 200),
                extra: { ecli: doc.props.ecli }
            }
        """
        return _two_phase_search(
            store,
            ecli_aql,
            {"ecli": intent["ecli"].upper(), "limit": limit},
            text_aql,
            {**tok_bind, "limit": limit},
            limit,
        )

    return list(store.query(text_aql, {**tok_bind, "limit": limit}))[:limit]


def _search_dossiers(
    store: ArangoStore,
    tokens: list[str],
    soort: list[str] | None,
    limit: int,
) -> list[dict[str, Any]]:
    clause, tok_bind = build_search_clause(tokens, ["titel", "display_name", "kamerstuknummer"])
    bind_vars: dict[str, Any] = {**tok_bind, "limit": limit}
    soort_clause = ""
    if soort:
        soort_clause = "FILTER LOWER(doc.props.huidige_fase) IN @soort_filter"
        bind_vars["soort_filter"] = [s.lower() for s in soort]
    aql = f"""
    FOR doc IN search_dossiers
        SEARCH {clause}
        {soort_clause}
        SORT BM25(doc) DESC
        LIMIT @limit
        RETURN {{
            id: doc._id, key: doc._key,
            collection: 'kamerstukdossiers', type: doc.type,
            display_name: (doc.props.titel != null ? doc.props.titel : doc.props.display_name),
            snippet: doc.props.kamerstuknummer,
            extra: {{
                kamerstuknummer: doc.props.kamerstuknummer,
                huidige_fase: doc.props.huidige_fase,
                afgedaan: doc.props.afgedaan
            }}
        }}
    """
    return list(store.query(aql, bind_vars))


def _search_commissies(
    store: ArangoStore, tokens: list[str], limit: int
) -> list[dict[str, Any]]:
    clause, tok_bind = build_search_clause(tokens, ["naam", "afkorting"])
    aql = f"""
    FOR doc IN search_commissies
        SEARCH {clause}
        SORT BM25(doc) DESC
        LIMIT @limit
        RETURN {{
            id: doc._id, key: doc._key,
            collection: 'commissies', type: doc.type,
            display_name: doc.props.naam,
            snippet: doc.props.afkorting,
            extra: {{ slug: doc.props.slug, afkorting: doc.props.afkorting }}
        }}
    """
    return list(store.query(aql, {**tok_bind, "limit": limit}))


def _search_leden(
    store: ArangoStore, tokens: list[str], limit: int
) -> list[dict[str, Any]]:
    aql = """
    FOR doc IN leden
        LET membership_labels = (
            FOR m IN (doc.props.fractielidmaatschappen OR [])
                RETURN CONCAT_SEPARATOR(" ",
                    m.afkorting != null ? m.afkorting : "",
                    m.naam != null ? m.naam : "",
                    CONCAT_SEPARATOR(" ", m.aliases OR [])
                )
        )
        LET haystack = LOWER(CONCAT_SEPARATOR(" ",
            doc.props.naam OR "",
            doc.props.partij OR "",
            CONCAT_SEPARATOR(" ", membership_labels)
        ))
        FILTER LENGTH(FOR t IN @tokens FILTER NOT CONTAINS(haystack, t) LIMIT 1 RETURN 1) == 0
        SORT doc.props.actief DESC, doc.props.naam ASC
        LIMIT @limit
        RETURN {
            id: doc._id, key: doc._key,
            collection: 'leden', type: doc.type,
            display_name: doc.props.naam,
            snippet: doc.props.partij,
            extra: { partij: doc.props.partij, actief: doc.props.actief }
        }
    """
    return list(store.query(aql, {"tokens": tokens, "limit": limit}))


def _search_fracties(
    store: ArangoStore, tokens: list[str], limit: int
) -> list[dict[str, Any]]:
    aql = """
    FOR doc IN fracties
        LET haystack = LOWER(CONCAT_SEPARATOR(" ",
            doc.props.naam OR "",
            doc.props.afkorting OR "",
            CONCAT_SEPARATOR(" ", doc.props.aliases OR [])
        ))
        FILTER LENGTH(FOR t IN @tokens FILTER NOT CONTAINS(haystack, t) LIMIT 1 RETURN 1) == 0
        SORT doc.props.actief DESC,
             (doc.props.aantal_zetels != null ? doc.props.aantal_zetels : 0) DESC,
             doc.props.naam ASC
        LIMIT @limit
        RETURN {
            id: doc._id, key: doc._key,
            collection: 'fracties', type: doc.type,
            display_name: doc.props.naam,
            snippet: doc.props.afkorting,
            extra: {
                afkorting: doc.props.afkorting,
                aantal_zetels: doc.props.aantal_zetels,
                actief: doc.props.actief
            }
        }
    """
    return list(store.query(aql, {"tokens": tokens, "limit": limit}))


def _search_publications(
    store: ArangoStore,
    tokens: list[str],
    soort: list[str] | None,
    limit: int,
) -> list[dict[str, Any]]:
    clause, tok_bind = build_search_clause(
        tokens, ["display_name", "title", "titel", "external_id"]
    )
    bind_vars: dict[str, Any] = {**tok_bind, "limit": limit}
    soort_clause = ""
    if soort:
        soort_clause = "FILTER LOWER(doc.props.soort) IN @soort_filter"
        bind_vars["soort_filter"] = [s.lower() for s in soort]
    # Hydrated PDF text isn't indexed in the view (~500 KB rows are too
    # bulky for sub-200-ms search); identifier and title fields cover
    # the UI use cases. A dedicated full-text endpoint can opt-in.
    aql = f"""
    FOR doc IN search_publications
        SEARCH {clause}
        {soort_clause}
        SORT BM25(doc) DESC
        LIMIT @limit
        RETURN {{
            id: doc._id, key: doc._key,
            collection: 'publications', type: doc.type,
            display_name: (doc.props.title != null ? doc.props.title : doc.props.display_name),
            snippet: doc.props.soort,
            extra: {{ soort: doc.props.soort, external_id: doc.props.external_id }}
        }}
    """
    return list(store.query(aql, bind_vars))


# ── Main search dispatcher ────────────────────────────────────────────────────


def search_all(
    store: ArangoStore,
    *,
    q: str,
    types: list[str],
    soort: list[str] | None = None,
    limit: int = 20,
) -> dict[str, list[dict[str, Any]]]:
    """Full-text search across requested entity types.

    Returns a dict keyed by type name with a list of hit dicts each containing
    {id, key, collection, type, display_name, snippet, extra}.

    Uses ArangoSearch views for indexed types and CONTAINS for small
    collections (leden, fracties). Every token must appear — AND semantics.
    """
    tokens = tokenize_search_query(q)
    if not tokens:
        return {t: [] for t in types}

    alias_map = load_instrument_alias_map(store) if "articles" in types else {}
    intent = parse_search_query(q, alias_map)

    results: dict[str, list[dict[str, Any]]] = {}
    for t in types:
        if t == "articles":
            results[t] = _search_articles(store, tokens, intent, limit)
        elif t == "instruments":
            results[t] = _search_instruments(store, tokens, limit)
        elif t == "judgments":
            results[t] = _search_judgments(store, tokens, intent, limit)
        elif t == "dossiers":
            results[t] = _search_dossiers(store, tokens, soort, limit)
        elif t == "commissies":
            results[t] = _search_commissies(store, tokens, limit)
        elif t == "leden":
            results[t] = _search_leden(store, tokens, limit)
        elif t == "fracties":
            results[t] = _search_fracties(store, tokens, limit)
        elif t == "publications":
            results[t] = _search_publications(store, tokens, soort, limit)
    return results
