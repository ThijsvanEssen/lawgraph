"""Full-text and structured search query helpers."""

from __future__ import annotations

import re
from typing import Any

from lawgraph.db import ArangoStore


def _build_search_clause(
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


def _tokenize_search_query(q: str) -> list[str]:
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


def _load_instrument_alias_map(store: ArangoStore) -> dict[str, str]:
    """Return a lowercased alias → bwb_id map for known instruments.

    Aliases come from each instrument's ``short_title``, ``citation_title``,
    and ``title`` props. The instruments collection is small (~tens of
    documents on a strafrecht profile) so a per-call AQL scan is cheap and
    keeps the map fresh without explicit invalidation.
    """
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
    return alias_map


def _parse_search_query(q: str, alias_map: dict[str, str]) -> dict[str, Any]:
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

    Uses CONTAINS matching across a per-collection haystack of relevant
    fields. The query is tokenised on whitespace and *every* token must
    appear in the haystack (AND-semantics) — so ``"strafvordering 537"``
    matches an article whose title mentions Strafvordering and whose
    article_number is 537. No dedicated search index required.
    """
    results: dict[str, list[dict[str, Any]]] = {}
    tokens = _tokenize_search_query(q)
    if not tokens:
        return {t: [] for t in types}

    # Single re-usable filter clause: every token in @tokens must appear in
    # the local LET haystack. Short-circuits via LIMIT 1 in the inner FOR.
    _all_tokens_filter = (
        "FILTER LENGTH(FOR t IN @tokens "
        "FILTER NOT CONTAINS(haystack, t) LIMIT 1 RETURN 1) == 0"
    )

    # Try to recognise structured patterns before falling back to AND-tokens.
    alias_map = _load_instrument_alias_map(store) if "articles" in types else {}
    intent = _parse_search_query(q, alias_map)

    # Pre-load the bwb → instrument enrichment dict once. Used to populate
    # extra.citation_title / extra.short_title on every article hit so the
    # frontend can render a parent-law label without a second roundtrip.
    _instrument_enrich_aql = """
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

    def _article_extra() -> str:
        return """{
            bwb_id: doc.props.bwb_id,
            article_number: doc.props.article_number,
            citation_title: bwb_to_inst[doc.props.bwb_id].citation_title,
            short_title: bwb_to_inst[doc.props.bwb_id].short_title
        }"""

    if "articles" in types:
        article_hits: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        # Intent-aware precise lookup: when the query parses as an article
        # reference, pull the exact match first so it always tops the list.
        if intent.get("kind") == "article" and intent.get("article_number"):
            precise_aql = f"""
            {_instrument_enrich_aql}
            FOR doc IN instrument_articles
                FILTER LOWER(doc.props.article_number) == @article_number
                FILTER @bwb_id == null OR doc.props.bwb_id == @bwb_id
                SORT doc.props.bwb_id ASC
                LIMIT @limit
                RETURN {{
                    id: doc._id,
                    key: doc._key,
                    collection: 'instrument_articles',
                    type: doc.type,
                    display_name: doc.props.display_name,
                    snippet: LEFT(doc.props.text, 200),
                    extra: {_article_extra()}
                }}
            """
            for row in store.query(
                precise_aql,
                {
                    "article_number": intent["article_number"],
                    "bwb_id": intent.get("bwb_id"),
                    "limit": limit,
                },
            ):
                rid = row.get("id")
                if rid and rid not in seen_ids:
                    seen_ids.add(rid)
                    article_hits.append(row)

        # Skip full-text scan when article-intent already matched: the precise
        # lookup is by definition the best answer, and a 60K-row CONTAINS scan
        # over article text dominates total latency. Run text search only as
        # the fallback path for free-form queries.
        skip_text_search = intent.get("kind") == "article" and len(article_hits) > 0
        if not skip_text_search and len(article_hits) < limit:
            # ArangoSearch view + BM25 ranking — orders of magnitude faster
            # than CONCAT+CONTAINS over the full collection.
            clause, tok_bind = _build_search_clause(
                tokens, ["display_name", "text", "article_number", "bwb_id"]
            )
            text_aql = f"""
            {_instrument_enrich_aql}
            FOR doc IN search_articles
                SEARCH {clause}
                SORT BM25(doc) DESC
                LIMIT @limit
                RETURN {{
                    id: doc._id,
                    key: doc._key,
                    collection: 'instrument_articles',
                    type: doc.type,
                    display_name: doc.props.display_name,
                    snippet: LEFT(doc.props.text, 200),
                    extra: {_article_extra()}
                }}
            """
            for row in store.query(text_aql, {**tok_bind, "limit": limit}):
                rid = row.get("id")
                if rid and rid not in seen_ids:
                    seen_ids.add(rid)
                    article_hits.append(row)
                    if len(article_hits) >= limit:
                        break

        results["articles"] = article_hits[:limit]

    if "instruments" in types:
        clause, tok_bind = _build_search_clause(
            tokens,
            [
                "title",
                "citation_title",
                "official_title",
                "display_name",
                "short_title",
                "bwb_id",
            ],
        )
        aql = f"""
        FOR doc IN search_instruments
            SEARCH {clause}
            SORT BM25(doc) DESC
            LIMIT @limit
            RETURN {{
                id: doc._id,
                key: doc._key,
                collection: 'instruments',
                type: doc.type,
                display_name: (
                    doc.props.citation_title != null ? doc.props.citation_title :
                    (doc.props.display_name != null ? doc.props.display_name : doc.props.title)
                ),
                snippet: LEFT(doc.props.title, 200),
                extra: {{
                    bwb_id: doc.props.bwb_id,
                    citation_title: doc.props.citation_title
                }}
            }}
        """
        results["instruments"] = list(store.query(aql, {**tok_bind, "limit": limit}))

    if "judgments" in types:
        judgment_hits: list[dict[str, Any]] = []
        seen_judgment_ids: set[str] = set()

        if intent.get("kind") == "ecli" and intent.get("ecli"):
            ecli_aql = """
            FOR doc IN judgments
                FILTER LOWER(doc.props.ecli) == @ecli
                LIMIT @limit
                RETURN {
                    id: doc._id,
                    key: doc._key,
                    collection: 'judgments',
                    type: doc.type,
                    display_name: doc.props.display_name,
                    snippet: LEFT(doc.props.summary, 200),
                    extra: { ecli: doc.props.ecli }
                }
            """
            for row in store.query(
                ecli_aql, {"ecli": intent["ecli"].lower(), "limit": limit}
            ):
                rid = row.get("id")
                if rid and rid not in seen_judgment_ids:
                    seen_judgment_ids.add(rid)
                    judgment_hits.append(row)

        # Same intent-shortcut as articles: skip text-scan when the ECLI
        # already gave us a hit. Long summary fields dominate scan cost.
        skip_text_search = intent.get("kind") == "ecli" and len(judgment_hits) > 0
        if not skip_text_search and len(judgment_hits) < limit:
            clause, tok_bind = _build_search_clause(
                tokens, ["display_name", "summary", "ecli", "appno"]
            )
            text_aql = f"""
            FOR doc IN search_judgments
                SEARCH {clause}
                SORT BM25(doc) DESC
                LIMIT @limit
                RETURN {{
                    id: doc._id,
                    key: doc._key,
                    collection: 'judgments',
                    type: doc.type,
                    display_name: doc.props.display_name,
                    snippet: LEFT(doc.props.summary, 200),
                    extra: {{ ecli: doc.props.ecli, appno: doc.props.appno }}
                }}
            """
            for row in store.query(text_aql, {**tok_bind, "limit": limit}):
                rid = row.get("id")
                if rid and rid not in seen_judgment_ids:
                    seen_judgment_ids.add(rid)
                    judgment_hits.append(row)
                    if len(judgment_hits) >= limit:
                        break

        results["judgments"] = judgment_hits[:limit]

    if "dossiers" in types:
        soort_clause = ""
        clause, tok_bind = _build_search_clause(
            tokens, ["titel", "display_name", "kamerstuknummer"]
        )
        bind_vars: dict[str, Any] = {**tok_bind, "limit": limit}
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
                id: doc._id,
                key: doc._key,
                collection: 'kamerstukdossiers',
                type: doc.type,
                display_name: (doc.props.titel != null ? doc.props.titel : doc.props.display_name),
                snippet: doc.props.kamerstuknummer,
                extra: {{
                    kamerstuknummer: doc.props.kamerstuknummer,
                    huidige_fase: doc.props.huidige_fase,
                    afgedaan: doc.props.afgedaan
                }}
            }}
        """
        results["dossiers"] = list(store.query(aql, bind_vars))

    if "commissies" in types:
        clause, tok_bind = _build_search_clause(tokens, ["naam", "afkorting"])
        aql = f"""
        FOR doc IN search_commissies
            SEARCH {clause}
            SORT BM25(doc) DESC
            LIMIT @limit
            RETURN {{
                id: doc._id,
                key: doc._key,
                collection: 'commissies',
                type: doc.type,
                display_name: doc.props.naam,
                snippet: doc.props.afkorting,
                extra: {{ slug: doc.props.slug, afkorting: doc.props.afkorting }}
            }}
        """
        results["commissies"] = list(store.query(aql, {**tok_bind, "limit": limit}))

    if "leden" in types:
        # Plain CONTAINS over leden — only ~4.5k docs, no view needed. Build
        # a haystack from naam + partij + every alias on every membership so
        # 'NSC' matches a lid whose canonical partij is 'Nieuw Sociaal Contract'.
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
                id: doc._id,
                key: doc._key,
                collection: 'leden',
                type: doc.type,
                display_name: doc.props.naam,
                snippet: doc.props.partij,
                extra: {
                    partij: doc.props.partij,
                    actief: doc.props.actief
                }
            }
        """
        results["leden"] = list(store.query(aql, {"tokens": tokens, "limit": limit}))

    if "fracties" in types:
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
                id: doc._id,
                key: doc._key,
                collection: 'fracties',
                type: doc.type,
                display_name: doc.props.naam,
                snippet: doc.props.afkorting,
                extra: {
                    afkorting: doc.props.afkorting,
                    aantal_zetels: doc.props.aantal_zetels,
                    actief: doc.props.actief
                }
            }
        """
        results["fracties"] = list(store.query(aql, {"tokens": tokens, "limit": limit}))

    if "publications" in types:
        soort_clause = ""
        clause, tok_bind = _build_search_clause(
            tokens, ["display_name", "title", "titel", "external_id"]
        )
        bind_vars_pub: dict[str, Any] = {**tok_bind, "limit": limit}
        if soort:
            soort_clause = "FILTER LOWER(doc.props.soort) IN @soort_filter"
            bind_vars_pub["soort_filter"] = [s.lower() for s in soort]

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
                id: doc._id,
                key: doc._key,
                collection: 'publications',
                type: doc.type,
                display_name: (doc.props.title != null ? doc.props.title : doc.props.display_name),
                snippet: doc.props.soort,
                extra: {{
                    soort: doc.props.soort,
                    external_id: doc.props.external_id
                }}
            }}
        """
        results["publications"] = list(store.query(aql, bind_vars_pub))

    return results
