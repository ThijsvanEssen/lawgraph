"""The types ``/api/search`` searches, one ``SearchType`` each (``SEARCHES``): what a hit of
each holds, how its search finds them, full and while typing."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import CHAMBER_EK, CHAMBER_TK
from lawgraph.core.dossier_numbers import short_title
from lawgraph.core.models import make_node_key
from lawgraph.db.queries import member_role
from lawgraph.db.queries._helpers import chamber_sql
from lawgraph.db.queries._json_sql import array_or_empty, first_present, is_present
from lawgraph.db.queries.search.clause import (
    Query,
    abbreviated_laws,
    legislated_dossiers,
    termed_articles,
)
from lawgraph.db.queries.search.persons import judgments_by_person, with_persons
from lawgraph.db.queries.search.ranking import folded
from lawgraph.db.queries.search.spec import Asked, Hit, SearchType
from lawgraph.db.queries.search.text import (
    LIVE_CANDIDATES,
    live_query,
    text_query,
    two_phase_search,
)
from lawgraph.db.schema import instrument_date_in_force, search_column, search_words

# ── articles ─────────────────────────────────────────────────────────────────

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
                FROM json_array_elements({array_or_empty("doc.props -> 'breadcrumb'")})
                    WITH ORDINALITY AS c(b, n)
                WHERE {is_present("b -> 'title'")}
            ),
            'instrument_title', {
    first_present(
        f"{_INSTRUMENT_PROPS} -> 'citation_title'", f"{_INSTRUMENT_PROPS} -> 'title'"
    )
},
            'citation_title', {_INSTRUMENT_PROPS} -> 'citation_title',
            'short_title', {_INSTRUMENT_PROPS} -> 'short_title'
        )
    )
"""


def _with_terms(
    hits: list[Hit], tokens: list[str], termed: list[list[str]] | None
) -> list[Hit]:
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
        termed=termed,
        laws=laws,
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
    return _with_terms(two_phase_search(store, precise, text, limit), tokens, termed)


# ── instruments ──────────────────────────────────────────────────────────────

_INSTRUMENT_HIT = f"""
    json_build_object(
        'id', doc.id, 'key', doc.key,
        'collection', 'instruments', 'type', doc.type,
        'display_name', {
    first_present(
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
            'aliases', doc.props -> 'aliases',
            'kind', doc.props -> 'kind',
            'date_published', doc.props -> 'date_published',
            'date_in_force', doc.props -> 'date_in_force',
            'version_date_in_force', doc.props -> 'version_date_in_force'
        )
    )
"""


def _search_instruments(kind: SearchType, asked: Asked, live: bool) -> list[Hit]:
    """Instruments whose alias or short title is the whole query first (``Boek 6 BW``,
    ``BW``), then those that hold its words."""
    store, limit, period = asked.store, asked.limit, asked.period
    precise: Query = (
        f"""
        SELECT {_INSTRUMENT_HIT} FROM instruments doc
        WHERE (doc.{search_column("aliases", "norm")} @> ARRAY[lg_fold(%(name)s)]
           OR doc.{search_column("short_title", "norm")} @> ARRAY[lg_fold(%(name)s)])
          {period.where(kind.period_date)}
        ORDER BY doc.citation_title NULLS FIRST, doc.key
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
    )
    return two_phase_search(store, precise, text, limit, precise_score=None)


# ── judgments ────────────────────────────────────────────────────────────────

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
# The judgments a live search looks for need this many characters: a part of a name or
# number of fewer is in too many.
LIVE_MIN_JUDGMENT = 3


def _search_judgments(kind: SearchType, asked: Asked, live: bool) -> list[Hit]:
    """Ranked: an ECLI; a judgment the query is the name of; those that hold its words;
    those that name a person it is. While typing: ``_judgments_while_typing``."""
    if live:
        return _judgments_while_typing(kind, asked)
    store, tokens, notation, limit = (
        asked.store,
        asked.tokens,
        asked.notation,
        asked.limit,
    )
    period, q = asked.period, asked.q
    text = text_query(
        kind,
        store,
        _JUDGMENT_HIT,
        tokens,
        limit,
        where=period.where(kind.period_date),
        params=period.params(),
    )
    if notation is not None and notation.kind == "ecli":
        ecli: Query = (
            f"""
            SELECT {_ECLI_HIT} FROM judgments doc
            WHERE doc.ecli = %(ecli)s {period.where(kind.period_date)}
            ORDER BY doc.key
            LIMIT %(limit)s
            """,
            {"ecli": notation.identifier, "limit": limit, **period.params()},
        )
        return two_phase_search(store, ecli, text, limit)

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
              {period.where(kind.period_date)}
            OFFSET 0
        ) doc
        ORDER BY doc.date_eff DESC NULLS LAST,
                 {is_present("doc.props -> 'translation_of'")},
                 doc.key
        LIMIT %(limit)s
        """,
        {"name": q.strip(), "limit": limit, **period.params()},
    )
    found = two_phase_search(store, name, text, limit)
    persons = judgments_by_person(
        store, tokens, limit, period, kind.period_date, typing=False
    )
    return with_persons(q, persons, found, limit)


def _judgments_while_typing(kind: SearchType, asked: Asked) -> list[Hit]:
    """The judgments a typed query names (``_judgments_named``) and those that name a
    person it is (``judgments_by_person``, the last word by its start); when none, the
    newest that hold its words."""
    named = _judgments_named(kind, asked)
    notation, q = asked.notation, asked.q
    if notation is not None and notation.kind == "ecli":
        return named
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
                where="AND doc.stub IS NOT TRUE AND doc.same_as IS NULL"
                + period.where(kind.period_date),
                params=period.params(),
            ),
            indexes_only=True,
        )
    )


def _judgments_named(kind: SearchType, asked: Asked) -> list[Hit]:
    """The judgments a typed query names, without ranking a summary: an ECLI; a judgment
    whose name holds the query (``Urgenda``, ``Lindenbaum``); then those whose display name
    holds every word of three characters or more, the most cited first."""
    store, notation, limit, period = (
        asked.store,
        asked.notation,
        asked.limit,
        asked.period,
    )
    if len(asked.q.strip()) < LIVE_MIN_JUDGMENT:
        return []
    if notation is not None and notation.kind == "ecli":
        return list(
            store.query(
                f"SELECT {_ECLI_HIT} FROM judgments doc WHERE doc.ecli = %(ecli)s"
                f"{period.where(kind.period_date)} ORDER BY doc.key LIMIT %(limit)s",
                {"ecli": notation.identifier, "limit": limit, **period.params()},
            )
        )
    words = [t for t in asked.tokens if len(t) >= LIVE_MIN_JUDGMENT]
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
                SELECT doc.id, row_number() OVER (
                    ORDER BY doc.inbound_citation_count DESC NULLS LAST, doc.key DESC
                ) AS n
                FROM (
                    SELECT * FROM judgments doc
                    WHERE doc.stub IS NOT TRUE AND doc.same_as IS NULL
                      AND {holds.format(column=column)} {period.where(kind.period_date)}
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


# ── dossiers, committees, documents ──────────────────────────────────────────

_KIND = "AND lower(doc.props ->> 'kind') = ANY(%(kind_filter)s)"
# The chamber of a document from its labels, as everywhere (``chamber_sql``): null for a
# Staatsblad or Staatscourant publication.
_CHAMBER = chamber_sql("doc")

# Words that name the type of a dossier rather than what it is about: "cbw dossier" asks for
# the dossier of the Cbw. Left out unless they are all that is asked.
_DOSSIER_WORDS = frozenset({"dossier", "dossiers"})

_DOSSIER_HIT = f"""
        json_build_object(
            'id', doc.id, 'key', doc.key,
            'collection', 'dossiers', 'type', doc.type,
            'display_name', {first_present("doc.props -> 'title'", "doc.props -> 'display_name'")},
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


def _search_dossiers(kind: SearchType, asked: Asked, live: bool) -> list[Hit]:
    store, kinds, period = asked.store, asked.kinds, asked.period
    words = [t for t in asked.tokens if t not in _DOSSIER_WORDS] or asked.tokens
    query = text_query(
        kind,
        store,
        _DOSSIER_HIT,
        words,
        asked.limit,
        where=(_KIND if kinds else "") + period.where(kind.period_date),
        params={"kind_filter": [k.lower() for k in kinds or []], **period.params()},
        live=live,
        termed=legislated_dossiers(store, words),
    )
    hits = list(store.query(*query, indexes_only=True))
    for hit in hits:
        # the name the dossier goes by, as /api/dossiers gives it ("Wet betaalbare huur")
        extra = hit["extra"]
        extra["short_title"] = short_title(extra.pop("title", None))
    return hits


_COMMITTEE_HIT = """
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


def _search_committees(kind: SearchType, asked: Asked, live: bool) -> list[Hit]:
    query = text_query(
        kind, asked.store, _COMMITTEE_HIT, asked.tokens, asked.limit, live=live
    )
    return list(asked.store.query(*query, indexes_only=True))


# Hydrated PDF text isn't indexed (~500 KB rows are too bulky for sub-200-ms search);
# identifier and title fields cover the UI use cases.
_DOCUMENT_HIT = f"""
        json_build_object(
            'id', doc.id, 'key', doc.key,
            'collection', 'documents', 'type', doc.type,
            'display_name', {first_present("doc.props -> 'title'", "doc.props -> 'display_name'")},
            'snippet', doc.props -> 'kind',
            'extra', json_build_object(
                'kind', doc.props -> 'kind',
                'external_id', doc.props -> 'external_id',
                'dossier_number', CASE WHEN json_typeof(doc.props -> 'dossier_numbers') = 'array'
                                       THEN doc.props -> 'dossier_numbers' -> 0 END,
                'sequence', doc.props -> 'sequence',
                'number', CASE {_CHAMBER}
                              WHEN '{CHAMBER_EK}' THEN doc.props ->> 'number'
                              WHEN '{CHAMBER_TK}' THEN doc.props ->> 'sequence'
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


def _search_documents(kind: SearchType, asked: Asked, live: bool) -> list[Hit]:
    kinds, period = asked.kinds, asked.period
    query = text_query(
        kind,
        asked.store,
        _DOCUMENT_HIT,
        asked.tokens,
        asked.limit,
        where=(_KIND if kinds else "") + period.where(kind.period_date),
        params={"kind_filter": [k.lower() for k in kinds or []], **period.params()},
        live=live,
    )
    return list(asked.store.query(*query, indexes_only=True))


# ── members, factions, cabinets, commitments, votes: every word in their names ─


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


def _all_words_folded(tokens: list[str], names: str) -> tuple[str, dict[str, Any]]:
    """``_all_words``, and a token also found in the folded *names*, both folded as the
    search folds them (``lg_fold``: ``yesilgoz`` finds Yeşilgöz), on a trigram index of
    their own (``schema._search_indexes``): ``search_names`` is lower case only."""
    params = {f"_word_{i}": token for i, token in enumerate(tokens)}
    condition = " AND ".join(
        f"(doc.search_names LIKE '%%' || lg_like(%({name})s) || '%%'"
        f" OR {names} LIKE '%%' || lg_like(lg_fold(%({name})s)) || '%%')"
        for name in params
    )
    return condition, params


def _search_members(kind: SearchType, asked: Asked, live: bool) -> list[Hit]:
    # a member's own name folded: the factions of a timeline are found as they are written
    condition, params = _all_words_folded(asked.tokens, "lg_fold(doc.name)")
    statement = f"""
        SELECT json_build_object(
            'id', doc.id, 'key', doc.key,
            'collection', 'members', 'type', doc.type,
            'display_name', doc.props -> 'name',
            'snippet', doc.props -> 'party',
            'extra', json_build_object(
                'party', doc.props -> 'party', 'active', doc.props -> 'active',
                'has_role', {member_role.has_role("doc")}
            )
        )
        FROM members doc
        WHERE {condition}
        ORDER BY {member_role.has_role("doc")} DESC, doc.active DESC NULLS LAST,
                 doc.name NULLS FIRST, doc.key
        LIMIT %(limit)s
        """
    return list(asked.store.query(statement, {**params, "limit": asked.limit}))


def _search_factions(kind: SearchType, asked: Asked, live: bool) -> list[Hit]:
    condition, params = _all_words_folded(asked.tokens, "lg_fold(doc.search_names)")
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
    return list(asked.store.query(statement, {**params, "limit": asked.limit}))


def _search_cabinets(kind: SearchType, asked: Asked, live: bool) -> list[Hit]:
    """Every word in the name of the cabinet (``kabinet-Schoof``), newest first."""
    condition, params = _all_words(asked.tokens, search_words("cabinets", "doc"))
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
    return list(asked.store.query(statement, {**params, "limit": asked.limit}))


def _search_commitments(kind: SearchType, asked: Asked, live: bool) -> list[Hit]:
    """Every word in the text or the number of the commitment (``TZ202609-011``), newest
    first."""
    period = asked.period
    condition, params = _all_words(asked.tokens, search_words("commitments", "doc"))
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
        WHERE {condition} {period.where(kind.period_date)}
        ORDER BY doc.made_on DESC NULLS LAST, doc.key
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


def _search_decisions(kind: SearchType, asked: Asked, live: bool) -> list[Hit]:
    """Every word (but those of ``_VOTE_WORDS``) in the subject or the kind of a vote,
    newest first; nothing when only such words are asked."""
    words = [t for t in asked.tokens if t not in _VOTE_WORDS]
    if not words:
        return []
    period = asked.period
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
        WHERE {condition} {period.where(kind.period_date)}
        ORDER BY doc.date DESC NULLS LAST, doc.key
        LIMIT %(limit)s
        """
    return list(
        asked.store.query(
            statement, {**params, **period.params(), "limit": asked.limit}
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
            live_order="doc.inbound_citation_count DESC NULLS LAST, doc.key",
            candidate_order="doc.inbound_citation_count DESC NULLS LAST, doc.key",
            citations="doc.inbound_citation_count",
            # the day its law came into force
            period_date=(
                "(SELECT "
                + instrument_date_in_force("i")
                + " FROM instruments i WHERE i.bwb_id = {row}.bwb_id ORDER BY i.key LIMIT 1)"
            ),
            heavy=True,
        ),
        SearchType(
            "judgments",
            _search_judgments,
            fields=["display_name", "names", "summary", "ecli", "appno"],
            live_order="doc.date_eff DESC NULLS LAST, doc.key DESC",
            candidate_order="doc.inbound_citation_count DESC NULLS LAST,"
            " doc.date_eff DESC NULLS LAST, doc.key",
            period_date="{row}.date_eff",  # the day of its decision
            heavy=True,
        ),
        SearchType(
            "documents",
            _search_documents,
            fields=["display_name", "title", "external_id"],
            live_order="doc.date DESC NULLS LAST, doc.key DESC",
            candidate_order="doc.date DESC NULLS LAST, doc.key",
            period_date="{row}.date",
            heavy=True,
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
            live_order="doc.article_count DESC NULLS LAST, doc.key",
            # the day it came into force, as the index ``instruments_date_in_force`` reads
            # it
            period_date=instrument_date_in_force("{row}"),
            heavy=True,
        ),
        SearchType(
            "dossiers",
            _search_dossiers,
            fields=["title", "display_name", "number"],
            live_order="doc.last_activity DESC NULLS LAST, doc.key DESC",
            period_date="{row}.opened_on",  # the day it was opened
        ),
        SearchType(
            "committees",
            _search_committees,
            fields=["name", "abbreviation"],
            live_order="doc.key",
        ),
        SearchType("members", _search_members),
        SearchType("factions", _search_factions),
        SearchType("cabinets", _search_cabinets),
        SearchType(
            "commitments",
            _search_commitments,
            period_date="{row}.made_on",  # the day it was made
        ),
        SearchType("decisions", _search_decisions, period_date="{row}.date"),
    )
}

# The collections ``/api/search`` can search, named as the collection is.
SEARCH_TYPES = frozenset(SEARCHES)
