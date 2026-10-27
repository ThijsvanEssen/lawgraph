"""The types ``/api/search`` searches, one ``SearchType`` each (``SEARCHES``): what a hit of
each holds, how its search finds them, full and while typing."""

from __future__ import annotations

import json
from typing import Any

from lawgraph.config.constants import CHAMBER_EK, CHAMBER_TK
from lawgraph.core.dossier_numbers import short_title
from lawgraph.core.models import make_node_key
from lawgraph.core.motion_kinds import kinds_named
from lawgraph.core.time import dutch_today
from lawgraph.core.validity import instrument_validity
from lawgraph.db import GraphStore
from lawgraph.db.queries import member_role
from lawgraph.db.queries._helpers import chamber_sql
from lawgraph.db.queries._json_sql import array_or_empty, first_present, is_present
from lawgraph.db.queries._words import STEM_MIN
from lawgraph.db.queries.feed_sql import decided_persons
from lawgraph.db.queries.search.clause import (
    Query,
    Termed,
    abbreviated_laws,
    joined,
    legislated_dossiers,
    termed_articles,
)
from lawgraph.db.queries.search.persons import judgments_by_person, with_persons
from lawgraph.db.queries.search.ranking import SCORE_TITLE, folded, score_hit
from lawgraph.db.queries.search.spec import (
    JUDGMENT_CITE_PROPS,
    Asked,
    Facet,
    Hit,
    Match,
    SearchType,
)
from lawgraph.db.queries.search.text import (
    LIVE_CANDIDATES,
    live_query,
    text_query,
    two_phase_search,
)
from lawgraph.db.queries.validity import article_end_sql
from lawgraph.db.schema import instrument_date_in_force, search_column, search_words

# ── articles ─────────────────────────────────────────────────────────────────

# The instrument of an article: the first by key with its BWB id, else with its CELEX id.
_ARTICLE_INSTRUMENT = """
    LEFT JOIN LATERAL (
        SELECT i.props FROM instruments i
        WHERE r.bwb_id IS NOT NULL AND i.bwb_id = r.bwb_id
        ORDER BY i.key LIMIT 1
    ) by_bwb ON true
    LEFT JOIN LATERAL (
        SELECT i.props FROM instruments i
        WHERE r.celex IS NOT NULL AND i.celex = r.celex
        ORDER BY i.key LIMIT 1
    ) by_celex ON true
"""
_INSTRUMENT_PROPS = "coalesce(by_bwb.props, by_celex.props)"

_ARTICLE_HIT = f"""
    json_build_object(
        'id', r.id, 'key', r.key,
        'collection', 'articles', 'type', r.type,
        'display_name', r.props -> 'display_name',
        'snippet', left(coalesce(r.props ->> 'text', ''), 200),
        'extra', json_build_object(
            'bwb_id', r.props -> 'bwb_id',
            'celex', r.props -> 'celex',
            'article_number', r.props -> 'article_number',
            'heading', r.props -> 'heading',
            'division_titles', (
                SELECT coalesce(json_agg(b -> 'title' ORDER BY n), '[]'::json)
                FROM json_array_elements({array_or_empty("r.props -> 'breadcrumb'")})
                    WITH ORDINALITY AS c(b, n)
                WHERE {is_present("b -> 'title'")}
            ),
            'instrument_title', {
    first_present(
        f"{_INSTRUMENT_PROPS} -> 'citation_title'", f"{_INSTRUMENT_PROPS} -> 'title'"
    )
},
            'citation_title', {_INSTRUMENT_PROPS} -> 'citation_title',
            'short_title', {_INSTRUMENT_PROPS} -> 'short_title',
            'instrument_abbreviation', r.props -> 'instrument_abbreviation',
            'expired_on', least(
                lg_str({_INSTRUMENT_PROPS} -> 'date_expired'), {article_end_sql("r")}
            )
        )
    )
"""


def _with_terms(hits: list[Hit], asked: Asked, termed: Termed | None) -> list[Hit]:
    """Each hit found by a term with ``extra.terms``: the words of the query it has as
    terms (the front end says where they come from: the case law); one the query names
    (``Termed.named``) scores as a whole name at least."""
    if termed:
        found = [set(ids) for ids in termed.ids]
        for hit in hits:
            words = [
                t
                for t, ids in zip(asked.tokens, found, strict=True)
                if hit["id"] in ids
            ]
            if words:
                hit["extra"]["terms"] = words
            if hit["id"] in termed.named:
                hit["score"] = max(
                    hit.get("score", score_hit(asked.q, hit)), SCORE_TITLE
                )
    return hits


def _articles_match(kind: SearchType, asked: Asked) -> Match:
    """The articles that hold the words, or whose law's abbreviation they are, or that
    their case law calls by them, in the period."""
    termed = termed_articles(asked.store, asked.tokens)
    return Match(
        asked.tokens,
        asked.period.where(kind.period_date),
        asked.period.params(),
        termed.ids if termed else None,
        abbreviated_laws(asked.store, asked.tokens),
    )


def _search_articles(kind: SearchType, asked: Asked, live: bool) -> list[Hit]:
    store, tokens, notation, limit = (
        asked.store,
        asked.tokens,
        asked.notation,
        asked.limit,
    )
    period = asked.period
    termed = termed_articles(store, tokens)
    laws = abbreviated_laws(store, tokens)
    in_period = period.where(kind.period_date)
    text = text_query(
        kind,
        store,
        _ARTICLE_HIT,
        tokens,
        limit,
        joins=_ARTICLE_INSTRUMENT,
        where=in_period,
        params=period.params(),
        live=live,
        termed=termed.ids if termed else None,
        laws=laws,
        named=termed.named if termed else None,
        any_word=asked.any_word,
    )
    if notation is None or notation.kind != "article":
        hits = list(store.query(*text, indexes_only=True))[:limit]
        return _with_terms(hits, asked, termed)

    # The law is named: the article is one key. It is not: every law with that number.
    keys = [make_node_key(a.law_id, a.number) for a in notation.articles if a.law_id]
    if keys:
        precise: Query = (
            f"""
            SELECT {_ARTICLE_HIT} FROM articles r {_ARTICLE_INSTRUMENT}
            WHERE r.key = ANY(%(keys)s) AND r.stub IS NOT TRUE {in_period}
            ORDER BY array_position(%(keys)s::text[], r.key)
            LIMIT %(limit)s
            """,
            {"keys": keys, "limit": limit, **period.params()},
        )
    else:
        precise = (
            f"""
            SELECT {_ARTICLE_HIT} FROM articles r {_ARTICLE_INSTRUMENT}
            WHERE r.article_number = ANY(%(numbers)s) AND r.stub IS NOT TRUE {in_period}
            ORDER BY r.bwb_id NULLS FIRST, r.key
            LIMIT %(limit)s
            """,
            {
                "numbers": [a.number for a in notation.articles],
                "limit": limit,
                **period.params(),
            },
        )
    # an article of a law the citation names is the one it names
    found = two_phase_search(store, precise, text, limit, exact=bool(keys))
    return _with_terms(found, asked, termed)


# ── instruments ──────────────────────────────────────────────────────────────

_INSTRUMENT_HIT = f"""
    json_build_object(
        'id', r.id, 'key', r.key,
        'collection', 'instruments', 'type', r.type,
        'display_name', {
    first_present(
        "r.props -> 'citation_title'",
        "r.props -> 'display_name'",
        "r.props -> 'title'",
    )
},
        'snippet', left(coalesce(r.props ->> 'title', ''), 200),
        'extra', json_build_object(
            'bwb_id', r.props -> 'bwb_id',
            'citation_title', r.props -> 'citation_title',
            'short_title', r.props -> 'short_title',
            'aliases', r.props -> 'aliases',
            'kind', r.props -> 'kind',
            'date_published', r.props -> 'date_published',
            'date_in_force', r.props -> 'date_in_force',
            'version_date_in_force', r.props -> 'version_date_in_force',
            'expired_on', lg_str(r.props -> 'date_expired')
        )
    )
"""


def _instruments_match(kind: SearchType, asked: Asked) -> Match:
    """The instruments that hold the words, in the period."""
    return Match(
        asked.tokens, asked.period.where(kind.period_date), asked.period.params()
    )


# The props ``instrument_validity`` reads, as JSON text.
_VALIDITY_PROPS = """json_build_object(
    'stub', r.props -> 'stub', 'date_expired', r.props -> 'date_expired',
    'date_in_force', r.props -> 'date_in_force', 'in_force', r.props -> 'in_force',
    'status', r.props -> 'status', 'bwb_id', r.props -> 'bwb_id',
    'celex', r.props -> 'celex'
)::text"""


def _validity_of(props: str | None) -> str | None:
    """The state today (``core.validity``) of the instrument with the JSON *props*; None
    where its source says nothing of it."""
    validity = instrument_validity(json.loads(props or "{}"), dutch_today().isoformat())
    return validity.state.value if validity else None


def _search_instruments(kind: SearchType, asked: Asked, live: bool) -> list[Hit]:
    """Instruments whose alias or short title is the whole query first (``Boek 6 BW``,
    ``BW``), then those that hold its words."""
    store, limit, period = asked.store, asked.limit, asked.period
    precise: Query = (
        f"""
        SELECT {_INSTRUMENT_HIT} FROM instruments r
        WHERE (r.{search_column("aliases", "norm")} @> ARRAY[lg_fold(%(name)s)]
           OR r.{search_column("short_title", "norm")} @> ARRAY[lg_fold(%(name)s)])
          {period.where(kind.period_date)}
        ORDER BY r.citation_title NULLS FIRST, r.key
        LIMIT %(limit)s
        """,
        {"name": folded(asked.q), "limit": limit, **period.params()},
    )
    text = text_query(
        kind,
        store,
        _INSTRUMENT_HIT,
        asked.tokens,
        limit,
        where=period.where(kind.period_date),
        params=period.params(),
        live=live,
        any_word=asked.any_word,
    )
    # a law whose abbreviation or short title is the query is the one it names
    return two_phase_search(store, precise, text, limit, precise_score=None, exact=True)


# What a hit of one node is made of, by the table it is in: its SQL and its joins.
_HIT_SQL = {
    "articles": (_ARTICLE_HIT, _ARTICLE_INSTRUMENT),
    "instruments": (_INSTRUMENT_HIT, ""),
}


def hit_by_key(store: GraphStore, table: str, key: str) -> Hit | None:
    """The node *key* of *table* (``articles`` or ``instruments``) as its search makes a
    hit of it, without a score; None when the graph does not have it."""
    hit_sql, joins = _HIT_SQL[table]
    rows: list[Hit] = list(
        store.query(
            f"SELECT {hit_sql} FROM {table} r {joins} WHERE r.key = %(key)s",
            {"key": key},
        )
    )
    return rows[0] if rows else None


# ── judgments ────────────────────────────────────────────────────────────────

_JUDGMENT_HIT = f"""
    json_build_object(
        'id', r.id, 'key', r.key,
        'collection', 'judgments', 'type', r.type,
        'display_name', r.props -> 'display_name',
        'snippet', left(coalesce(r.props ->> 'summary', ''), 200),
        'extra', json_build_object(
            'ecli', r.props -> 'ecli',
            'appno', r.props -> 'appno',
            'names', r.props -> 'names'
        ),
        {JUDGMENT_CITE_PROPS}
    )
"""
_ECLI_HIT = f"""
    json_build_object(
        'id', r.id, 'key', r.key,
        'collection', 'judgments', 'type', r.type,
        'display_name', r.props -> 'display_name',
        'snippet', left(coalesce(r.props ->> 'summary', ''), 200),
        'extra', json_build_object('ecli', r.props -> 'ecli'),
        {JUDGMENT_CITE_PROPS}
    )
"""
# The judgments a live search looks for need this many characters: a part of a name or
# number of fewer is in too many.
LIVE_MIN_JUDGMENT = 3


def _judgments_match(kind: SearchType, asked: Asked) -> Match:
    """The judgments that hold the words, in the period."""
    return Match(
        asked.tokens, asked.period.where(kind.period_date), asked.period.params()
    )


def _search_judgments(kind: SearchType, asked: Asked, live: bool) -> list[Hit]:
    """Ranked: an ECLI; a judgment the query is the name of; those that hold its words;
    those that name a person it is. While typing: ``_judgments_while_typing``."""
    if live:
        return _judgments_while_typing(kind, asked)
    store, tokens, limit = asked.store, asked.tokens, asked.limit
    period, q = asked.period, asked.q
    text = text_query(
        kind,
        store,
        _JUDGMENT_HIT,
        tokens,
        limit,
        where=period.where(kind.period_date),
        params=period.params(),
        any_word=asked.any_word,
    )
    identified = _identified_judgments(kind, asked)
    if identified is not None:
        return two_phase_search(store, identified, text, limit, exact=True)

    # The query may be the name of a judgment ("Urgenda", "Lindenbaum/Cohen"): those first,
    # the latest decision first (of one case: the highest court), a translation after the
    # judgment it translates. The judgments of that name are found first, on their own
    # (OFFSET 0): the planner expects 0.5% of the rows to hold any name, and would walk the
    # index of the dates for them (on the full graph every row, 2.6 s, for a name none has).
    name: Query = (
        f"""
        SELECT {_JUDGMENT_HIT}
        FROM (
            SELECT * FROM judgments r
            WHERE r.{search_column("names", "norm")} @> ARRAY[lg_fold(%(name)s)]
              {period.where(kind.period_date)}
            OFFSET 0
        ) r
        ORDER BY r.date_eff DESC NULLS LAST,
                 {is_present("r.props -> 'translation_of'")},
                 r.key
        LIMIT %(limit)s
        """,
        {"name": q.strip(), "limit": limit, **period.params()},
    )
    found = two_phase_search(store, name, text, limit, exact=True)
    persons = judgments_by_person(
        store, tokens, limit, period, kind.period_date, typing=False
    )
    return with_persons(q, persons, found, limit)


def _judgments_while_typing(kind: SearchType, asked: Asked) -> list[Hit]:
    """The judgments a typed query names (``_judgments_named``) and those that name a
    person it is (``judgments_by_person``, the last word by its start); when none, the
    newest that hold its words."""
    named = _judgments_named(kind, asked)
    if named and named[0].get("exact") or _is_ecli(asked):
        return named
    q = asked.q
    persons = (
        judgments_by_person(
            asked.store,
            asked.tokens,
            asked.limit,
            asked.period,
            kind.period_date,
            typing=True,
        )
        if len(q.strip()) >= LIVE_MIN_JUDGMENT
        else []
    )
    if named or persons:
        return with_persons(q, persons, named, asked.limit)
    return _judgments_with_words(kind, asked)


def _judgments_with_words(kind: SearchType, asked: Asked) -> list[Hit]:
    """The judgments that hold every word (in their summary, name or display name), the
    newest first of the first ``LIVE_CANDIDATES`` found, without a rank (``live_query``);
    none for a query shorter than ``LIVE_MIN_JUDGMENT``, as by name."""
    if len(asked.q.strip()) < LIVE_MIN_JUDGMENT:
        return []
    period = asked.period
    return list(
        asked.store.query(
            *live_query(
                kind,
                _JUDGMENT_HIT,
                asked.tokens,
                asked.limit,
                where="AND r.stub IS NOT TRUE AND r.same_as IS NULL"
                + period.where(kind.period_date),
                params=period.params(),
                any_word=asked.any_word,
            ),
            indexes_only=True,
        )
    )


# A judgment by the LJN that is the number of its ECLI (``core.ecli.LJN_ECLI``): the end of
# the ECLI, on the trigrams of its column of prefixes.
_BY_LJN = f"r.{search_column('ecli', 'prefix')} LIKE '%%:' || %(ljn)s"


def _identified_judgments(kind: SearchType, asked: Asked) -> Query | None:
    """The judgment the query identifies, an ECLI or an LJN (``LJN AU3313``: the judgment
    whose ECLI ends in it, ``ECLI:NL:HR:2005:AU3313``); None for a query that is neither."""
    notation, period = asked.notation, asked.period
    if notation is None or notation.kind not in ("ecli", "ljn"):
        return None
    where = "r.ecli = %(ecli)s" if notation.kind == "ecli" else _BY_LJN
    return (
        f"""
        SELECT {_ECLI_HIT} FROM judgments r
        WHERE {where} {period.where(kind.period_date)}
        ORDER BY r.key
        LIMIT %(limit)s
        """,
        {
            "ecli": notation.identifier,
            "ljn": notation.identifier,
            "limit": asked.limit,
            **period.params(),
        },
    )


def _is_ecli(asked: Asked) -> bool:
    """Whether the query is an ECLI: what no judgment has, none has (an LJN of none may be
    words: ``IB2001``)."""
    return asked.notation is not None and asked.notation.kind == "ecli"


def _judgments_named(kind: SearchType, asked: Asked) -> list[Hit]:
    """The judgments a typed query names, without ranking a summary: an ECLI; a judgment
    whose name holds the query (``Urgenda``, ``Lindenbaum``); then those whose display name
    holds every word of three characters or more, the most cited first."""
    store, limit, period = asked.store, asked.limit, asked.period
    if len(asked.q.strip()) < LIVE_MIN_JUDGMENT:
        return []
    identified = _identified_judgments(kind, asked)
    if identified is not None:
        known = [{**hit, "exact": True} for hit in store.query(*identified)]
        if known or _is_ecli(asked):
            return known
    words = [t for t in asked.tokens if len(t) >= LIVE_MIN_JUDGMENT]
    if not words:
        return []
    params: dict[str, Any] = {f"_w{n}": w for n, w in enumerate(words)}
    params["limit"] = limit
    params.update(period.params())
    holds = joined(
        [
            f"r.{{column}} LIKE '%%' || lg_like(lg_fold(%(_w{n})s)) || '%%'"
            for n in range(len(words))
        ],
        asked.any_word,
    )
    params["candidates"] = LIVE_CANDIDATES
    found: list[Hit] = []
    for column in (
        search_column("names", "ngram"),
        search_column("display_name", "ngram"),
    ):
        # the first ``LIVE_CANDIDATES`` found, then ordered: the index of the citations
        # would be walked for a part the planner thinks common, every row for a rare one
        statement = f"""
            SELECT {_JUDGMENT_HIT}
            FROM (
                SELECT r.id, row_number() OVER (
                    ORDER BY r.inbound_citation_count DESC NULLS LAST, r.key DESC
                ) AS n
                FROM (
                    SELECT * FROM judgments r
                    WHERE r.stub IS NOT TRUE AND r.same_as IS NULL
                      AND {holds.format(column=column)} {period.where(kind.period_date)}
                    LIMIT %(candidates)s
                ) r
                ORDER BY n
                LIMIT %(limit)s
            ) top
            JOIN judgments r ON r.id = top.id
            ORDER BY top.n
            """
        seen = {hit["id"] for hit in found}
        found += [
            hit for hit in store.query(statement, params) if hit["id"] not in seen
        ]
        if len(found) >= limit:
            break
    return found[:limit]


# ── dossiers, committees, documents ──────────────────────────────────────────

_KIND = "AND lower(r.props ->> 'kind') = ANY(%(kind_filter)s)"
# The chamber of a document from its labels, as everywhere (``chamber_sql``): null for a
# Staatsblad or Staatscourant publication.
_CHAMBER = chamber_sql("r")

# Words that name the type of a dossier rather than what it is about: "cbw dossier" asks for
# the dossier of the Cbw. Left out unless they are all that is asked.
_DOSSIER_WORDS = frozenset({"dossier", "dossiers"})

_DOSSIER_HIT = f"""
        json_build_object(
            'id', r.id, 'key', r.key,
            'collection', 'dossiers', 'type', r.type,
            'display_name', {first_present("r.props -> 'title'", "r.props -> 'display_name'")},
            'snippet', r.props -> 'label',
            'extra', json_build_object(
                'number', r.props -> 'label',
                'kind', r.props -> 'kind',
                'current_phase', r.props -> 'current_phase',
                'closed', r.props -> 'closed',
                'outcome', r.props -> 'outcome',
                'title', r.props -> 'title'
            )
        )
    """


def _dossiers_match(kind: SearchType, asked: Asked) -> Match:
    """The dossiers of the kinds asked for that hold the words (but those that name the
    type), or that the abbreviation of the law they made is, in the period."""
    words = [t for t in asked.tokens if t not in _DOSSIER_WORDS] or asked.tokens
    return Match(
        words,
        (_KIND if asked.kinds else "") + asked.period.where(kind.period_date),
        {
            "kind_filter": [k.lower() for k in asked.kinds or []],
            **asked.period.params(),
        },
        legislated_dossiers(asked.store, words),
    )


def _search_dossiers(kind: SearchType, asked: Asked, live: bool) -> list[Hit]:
    match = _dossiers_match(kind, asked)
    query = text_query(
        kind,
        asked.store,
        _DOSSIER_HIT,
        match.tokens,
        asked.limit,
        where=match.where,
        params=match.params,
        live=live,
        termed=match.termed,
        any_word=asked.any_word,
    )
    hits = list(asked.store.query(*query, indexes_only=True))
    for hit in hits:
        # the name the dossier goes by, as /api/dossiers gives it ("Wet betaalbare huur")
        extra = hit["extra"]
        extra["short_title"] = short_title(extra.pop("title", None))
    return hits


_COMMITTEE_HIT = """
        json_build_object(
            'id', r.id, 'key', r.key,
            'collection', 'committees', 'type', r.type,
            'display_name', r.props -> 'name',
            'snippet', r.props -> 'abbreviation',
            'extra', json_build_object(
                'slug', r.props -> 'slug', 'abbreviation', r.props -> 'abbreviation'
            )
        )
    """


def _search_committees(kind: SearchType, asked: Asked, live: bool) -> list[Hit]:
    query = text_query(
        kind,
        asked.store,
        _COMMITTEE_HIT,
        asked.tokens,
        asked.limit,
        live=live,
        any_word=asked.any_word,
    )
    return list(asked.store.query(*query, indexes_only=True))


# Hydrated PDF text isn't indexed (~500 KB rows are too bulky for sub-200-ms search);
# identifier and title fields cover the UI use cases.
_DOCUMENT_HIT = f"""
        json_build_object(
            'id', r.id, 'key', r.key,
            'collection', 'documents', 'type', r.type,
            'display_name', {first_present("r.props -> 'title'", "r.props -> 'display_name'")},
            'snippet', r.props -> 'kind',
            'extra', json_build_object(
                'kind', r.props -> 'kind',
                'external_id', r.props -> 'external_id',
                'dossier_number', CASE WHEN json_typeof(r.props -> 'dossier_numbers') = 'array'
                                       THEN r.props -> 'dossier_numbers' -> 0 END,
                'sequence', r.props -> 'sequence',
                'number', CASE {_CHAMBER}
                              WHEN '{CHAMBER_EK}' THEN r.props ->> 'number'
                              WHEN '{CHAMBER_TK}' THEN r.props ->> 'sequence'
                          END,
                'date', r.props -> 'date',
                'chamber', {_CHAMBER}
            ),
            -- what its readable address is built from: its own dossier, not a label
            'path_props', json_build_object(
                'dossier_number', r.dossier_number,
                'dossier_suffix', r.props -> 'dossier_suffix',
                'sequence', r.props -> 'sequence',
                'number', r.props -> 'number'
            )
        )
    """


# The motions of the kinds asked for (``%(motion_kinds)s``), by the partial index
# ``lg_document_light_motion_kind``.
_MOTIONS_OF_KINDS = """
    SELECT l.id FROM lg_document_light l
    WHERE lg_str(l.props -> 'motion_kind') = ANY(%(motion_kinds)s::text[])
"""


def _documents_match(kind: SearchType, asked: Asked) -> Match:
    """The papers of the kinds asked for that hold the words, of the factions the query
    names and the motions asked for, in the period; a word of the name of a kind of motion
    also finds the motions of that kind."""
    words = asked.words(kind)
    signed, signed_params = asked.signed_where(kind)
    motions = f" AND r.id IN ({_MOTIONS_OF_KINDS})" if asked.motion_kinds else ""
    return Match(
        words,
        (_KIND if asked.kinds else "")
        + asked.period.where(kind.period_date)
        + signed
        + motions,
        {
            "kind_filter": [k.lower() for k in asked.kinds or []],
            "motion_kinds": asked.motion_kinds,
            **asked.period.params(),
            **signed_params,
        },
        _motions_named(asked.store, words),
    )


def _search_documents(kind: SearchType, asked: Asked, live: bool) -> list[Hit]:
    """The papers that hold the words, of the factions the query names; a word of the name
    of a kind of motion (``wantrouwen``) also finds the motions of that kind, which rank
    above those that only hold the word."""
    match = _documents_match(kind, asked)
    query = text_query(
        kind,
        asked.store,
        _DOCUMENT_HIT,
        match.tokens,
        asked.limit,
        where=match.where,
        params=match.params,
        live=live,
        termed=match.termed,
        any_word=asked.any_word,
    )
    return list(asked.store.query(*query, indexes_only=True))


def _motions_named(store: GraphStore, words: list[str]) -> list[list[str]] | None:
    """Per word the motions of the kinds whose name holds it (``kinds_named``): a name of
    each, as a word of its title would be. None when no word names a kind."""
    kinds = [kinds_named(word) for word in words]
    if not any(kinds):
        return None
    rows = store.query(
        """
        SELECT lg_str(l.props -> 'motion_kind') AS kind, array_agg(l.id) AS ids
        FROM lg_document_light l
        WHERE lg_str(l.props -> 'motion_kind') = ANY(%(motion_kinds)s::text[])
        GROUP BY 1
        """,
        {"motion_kinds": sorted({k for named in kinds for k in named})},
    )
    of_kind = {row["kind"]: row["ids"] for row in rows}
    return [sorted(i for k in named for i in of_kind.get(k, [])) for named in kinds]


# ── members, factions, cabinets, commitments, votes: every word in their names ─


def _all_words(
    tokens: list[str],
    words: str = "r.search_names",
    any_word: bool = False,
    also: dict[int, str] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Every token (with *any_word*: one at least) is a part of *words* (the words of a
    cabinet, commitment or vote: lower case), or its stem is (``lg_tokens``, of
    ``STEM_MIN`` characters or more: "pensioenen" finds "pensioen"): a trigram lookup each.
    *also*: per token a condition that finds a row besides its words."""
    params = {f"_word_{i}": token for i, token in enumerate(tokens)}
    stem = "(lg_tokens(%({name})s))[1]"
    condition = joined(
        [
            f"({words} LIKE '%%' || lg_like(%({name})s) || '%%'"
            f" OR (char_length({stem.format(name=name)}) >= {STEM_MIN}"
            f" AND {words} LIKE '%%' || lg_like({stem.format(name=name)}) || '%%')"
            + (f" OR {also[i]}" if also and i in also else "")
            + ")"
            for i, name in enumerate(params)
        ],
        any_word,
    )
    return condition, params


def _all_words_folded(
    tokens: list[str], names: str, any_word: bool = False
) -> tuple[str, dict[str, Any]]:
    """Every token (with *any_word*: one at least) is a part of ``search_names`` or of the
    folded *names*, both folded as the search folds them (``lg_fold``: ``yesilgoz`` finds
    Yeşilgöz), on a trigram index of their own (``schema._search_indexes``):
    ``search_names`` is lower case only."""
    params = {f"_word_{i}": token for i, token in enumerate(tokens)}
    condition = joined(
        [
            f"(r.search_names LIKE '%%' || lg_like(%({name})s) || '%%'"
            f" OR {names} LIKE '%%' || lg_like(lg_fold(%({name})s)) || '%%')"
            for name in params
        ],
        any_word,
    )
    return condition, params


def _search_members(kind: SearchType, asked: Asked, live: bool) -> list[Hit]:
    # a member's own name folded: the factions of a timeline are found as they are written
    condition, params = _all_words_folded(
        asked.tokens, "lg_fold(r.name)", asked.any_word
    )
    statement = f"""
        SELECT json_build_object(
            'id', r.id, 'key', r.key,
            'collection', 'members', 'type', r.type,
            'display_name', r.props -> 'name',
            'snippet', r.props -> 'party',
            'extra', json_build_object(
                'party', r.props -> 'party', 'active', r.seated,
                'has_role', {member_role.has_role("r")}
            )
        )
        FROM members r
        WHERE {condition}
        ORDER BY {member_role.has_role("r")} DESC, r.seated DESC NULLS LAST,
                 r.name NULLS FIRST, r.key
        LIMIT %(limit)s
        """
    return list(asked.store.query(statement, {**params, "limit": asked.limit}))


def _search_factions(kind: SearchType, asked: Asked, live: bool) -> list[Hit]:
    condition, params = _all_words_folded(
        asked.tokens, "lg_fold(r.search_names)", asked.any_word
    )
    statement = f"""
        SELECT json_build_object(
            'id', r.id, 'key', r.key,
            'collection', 'factions', 'type', r.type,
            'display_name', r.props -> 'name',
            'snippet', r.props -> 'abbreviation',
            'extra', json_build_object(
                'abbreviation', r.props -> 'abbreviation',
                'seats', r.props -> 'seats',
                'active', r.props -> 'active'
            )
        )
        FROM factions r
        WHERE {condition}
        ORDER BY r.active DESC NULLS LAST, coalesce(r.seats, 0) DESC,
                 r.name NULLS FIRST, r.key
        LIMIT %(limit)s
        """
    return list(asked.store.query(statement, {**params, "limit": asked.limit}))


def _search_cabinets(kind: SearchType, asked: Asked, live: bool) -> list[Hit]:
    """Every word in the name of the cabinet (``kabinet-Schoof``), newest first."""
    condition, params = _all_words(
        asked.tokens, search_words("cabinets", "r"), asked.any_word
    )
    statement = f"""
        SELECT json_build_object(
            'id', r.id, 'key', r.key,
            'collection', 'cabinets', 'type', r.type,
            'display_name', r.props -> 'name',
            'snippet', r.props -> 'from_date',
            'extra', json_build_object(
                'from_date', r.props -> 'from_date',
                'to_date', r.props -> 'to_date'
            )
        )
        FROM cabinets r
        WHERE {condition}
        ORDER BY lg_str(r.props -> 'from_date') DESC NULLS LAST, r.key
        LIMIT %(limit)s
        """
    return list(asked.store.query(statement, {**params, "limit": asked.limit}))


# Words that name the type of a commitment rather than what it is about: "toezeggingen
# pensioenen" asks for the commitments on pensions. Left out unless they are all that is asked.
_COMMITMENT_WORDS = frozenset({"toezegging", "toezeggingen"})


def _search_commitments(kind: SearchType, asked: Asked, live: bool) -> list[Hit]:
    """Every word (but those of ``_COMMITMENT_WORDS``) in the text or the number of the
    commitment (``TZ202609-011``), newest first."""
    period = asked.period
    words = [t for t in asked.tokens if t not in _COMMITMENT_WORDS] or asked.tokens
    condition, params = _all_words(
        words, search_words("commitments", "r"), asked.any_word
    )
    statement = f"""
        SELECT json_build_object(
            'id', r.id, 'key', r.key,
            'collection', 'commitments', 'type', r.type,
            'display_name', r.props -> 'display_name',
            'snippet', r.props -> 'number',
            'extra', json_build_object(
                'number', r.props -> 'number',
                'made_on', r.props -> 'made_on',
                'status', r.props -> 'status',
                'minister_name', r.props -> 'minister_name',
                'cabinet', r.props -> 'cabinet',
                'ministry', r.props -> 'ministry'
            )
        )
        FROM commitments r
        WHERE {condition} {period.where(kind.period_date)}
        ORDER BY r.made_on DESC NULLS LAST, r.key
        LIMIT %(limit)s
        """
    return list(
        asked.store.query(
            statement, {**params, **period.params(), "limit": asked.limit}
        )
    )


# Words that name the type of a vote rather than what it was on: "stemming abortus" asks
# for the votes on abortion, and no subject holds "stemming".
_VOTE_WORDS = frozenset({"stemming", "stemmingen", "besluit", "besluiten"})


# The newest votes the search of the votes tests first, in the order of
# ``decisions_list_date``: of a common word ("motie", "wet") the first hits are among them.
DECISIONS_RECENT = 2000

_DECISION_HIT = """
    json_build_object(
        'id', r.id, 'key', r.key,
        'collection', 'decisions', 'type', r.type,
        'display_name', r.props -> 'display_name',
        'snippet', r.props -> 'subject',
        'extra', json_build_object(
            'date', r.props -> 'date',
            'kind', r.props -> 'kind',
            'passed', r.props -> 'passed',
            'chamber', r.props -> 'chamber',
            'dossier_numbers', r.props -> 'dossier_numbers'
        )
    )
"""
_NEWEST_FIRST = "date DESC NULLS LAST, key"
# The kind of motion a vote was on, as the partial index ``decisions_motion_kind`` reads it.
_MOTION_KIND = "lg_str(r.props -> 'motion_kind')"


def _search_decisions(kind: SearchType, asked: Asked, live: bool) -> list[Hit]:
    """Every word (but those of ``_VOTE_WORDS``) in the subject or the kind of a vote,
    newest first; nothing when only such words are asked.

    The ``DECISIONS_RECENT`` newest votes are tested first; when they hold fewer hits than
    asked, every vote that holds the words is found by the trigram index of their words,
    and ordered then. Not the votes newest first until enough hold them: the planner
    cannot count how few votes hold a rare word, and walked them all (prod, 16 Oct: 21,601
    votes read for the 20 of "huurverhoging", 4 s from disk)."""
    words = [t for t in asked.words(kind) if t not in _VOTE_WORDS]
    if not words:
        return []
    named = {i: kinds_named(word) for i, word in enumerate(words)}
    condition, params = _all_words(
        words,
        search_words("decisions", "r"),
        asked.any_word,
        # a word of the name of a kind of motion (``wantrouwen``): the votes on those
        {
            i: f"{_MOTION_KIND} = ANY(%(_kinds_{i})s::text[])"
            for i, k in named.items()
            if k
        },
    )
    params.update({f"_kinds_{i}": k for i, k in named.items() if k})
    signed, signed_params = asked.signed_where(kind)
    params.update(signed_params)
    if asked.motion_kinds:
        signed += f" AND {_MOTION_KIND} = ANY(%(motion_kinds)s::text[])"
        params["motion_kinds"] = asked.motion_kinds
    where = f"{condition} {asked.period.where(kind.period_date)}{signed}"
    statement = f"""
        WITH recent AS MATERIALIZED (
            SELECT r.id, r.date, r.key
            FROM (
                SELECT id, date, key, props FROM decisions
                ORDER BY {_NEWEST_FIRST} LIMIT %(recent)s
            ) r
            WHERE {where}
            ORDER BY r.date DESC NULLS LAST, r.key LIMIT %(limit)s
        ), found AS MATERIALIZED (
            SELECT r.id, r.date, r.key FROM decisions r
            WHERE (SELECT count(*) FROM recent) < %(limit)s AND {where}
        )
        SELECT {_DECISION_HIT}
        FROM (
            SELECT * FROM recent UNION SELECT * FROM found
            ORDER BY {_NEWEST_FIRST} LIMIT %(limit)s
        ) top
        JOIN decisions r ON r.id = top.id
        ORDER BY r.date DESC NULLS LAST, r.key
        """
    return list(
        asked.store.query(
            statement,
            {
                **params,
                **asked.period.params(),
                "recent": DECISIONS_RECENT,
                "limit": asked.limit,
            },
            indexes_only=True,
        )
    )


# ── the types ─────────────────────────────────────────────────────────────────

# The heavy types first, slowest first (``SearchType.heavy``): the order in which they take
# the threads of the pool.
SEARCHES: dict[str, SearchType] = {
    kind.table: kind
    for kind in (
        SearchType(
            "articles",
            _search_articles,
            fields=[
                "display_name",
                "heading",
                "breadcrumb.title",
                "text",
                "article_number",
                "bwb_id",
            ],
            # a word in the heading of an article weighs most, one in the title of a
            # division it stands in (titel, afdeling) more than one in its text
            boosts={"heading": 4.0, "display_name": 2.0, "breadcrumb.title": 1.5},
            # its own name is its heading; its law's name is in its display name, which
            # every article of the law holds (``score_hit``)
            names=("display_name", "heading"),
            titles=("heading", "breadcrumb.title"),
            live_order="r.inbound_citation_count DESC NULLS LAST, r.key",
            candidate_order="r.inbound_citation_count DESC NULLS LAST, r.key",
            citations="r.inbound_citation_count",
            # the day its law came into force
            period_date=(
                "(SELECT "
                + instrument_date_in_force("i")
                + " FROM instruments i WHERE i.bwb_id = {row}.bwb_id ORDER BY i.key LIMIT 1)"
            ),
            heavy=True,
            match=_articles_match,
        ),
        SearchType(
            "judgments",
            _search_judgments,
            fields=["display_name", "names", "summary", "ecli", "appno"],
            live_order="r.date_eff DESC NULLS LAST, r.key DESC",
            candidate_order="r.inbound_citation_count DESC NULLS LAST,"
            " r.date_eff DESC NULLS LAST, r.key",
            period_date="{row}.date_eff",  # the day of its decision
            heavy=True,
            match=_judgments_match,
            # its tier (the instance), and the year of its decision
            facets=(
                Facet("tier", "r.tier"),
                Facet("year", "left(r.date_eff, 4)", by_value=True),
            ),
        ),
        SearchType(
            "documents",
            _search_documents,
            fields=["display_name", "title", "external_id"],
            live_order="r.date DESC NULLS LAST, r.key DESC",
            candidate_order="r.date DESC NULLS LAST, r.key",
            period_date="{row}.date",
            heavy=True,
            signatures=lambda row: f"{row}.pj_actors",
            match=_documents_match,
            facets=(Facet("kind", "r.kind"),),
        ),
        SearchType(
            "instruments",
            _search_instruments,
            fields=[
                "title",
                "citation_title",
                "official_title",
                "display_name",
                "short_title",
                "aliases",
                "bwb_id",
            ],
            # a word in a name a law is cited by weighs more than one in its long title
            boosts={"aliases": 3.0, "short_title": 3.0, "citation_title": 2.0},
            live_order="r.article_count DESC NULLS LAST, r.key",
            # the day it came into force, as the index ``instruments_date_in_force`` reads
            # it
            period_date=instrument_date_in_force("{row}"),
            heavy=True,
            match=_instruments_match,
            facets=(Facet("validity", _VALIDITY_PROPS, _validity_of),),
        ),
        SearchType(
            "dossiers",
            _search_dossiers,
            fields=["title", "display_name", "number"],
            live_order="r.last_activity DESC NULLS LAST, r.key DESC",
            period_date="{row}.opened_on",  # the day it was opened
            match=_dossiers_match,
        ),
        SearchType(
            "committees",
            _search_committees,
            fields=["name", "abbreviation"],
            live_order="r.key",
        ),
        SearchType("members", _search_members),
        SearchType("factions", _search_factions),
        SearchType("cabinets", _search_cabinets),
        SearchType(
            "commitments",
            _search_commitments,
            period_date="{row}.made_on",  # the day it was made
        ),
        SearchType(
            "decisions",
            _search_decisions,
            period_date="{row}.date",
            # those of the paper it decided
            signatures=decided_persons,
        ),
    )
}

# The collections ``/api/search`` can search, named as the collection is.
SEARCH_TYPES = frozenset(SEARCHES)
