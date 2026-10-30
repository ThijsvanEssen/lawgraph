"""The reads and updates of the semantic phase for Rechtspraak and the ECHR: the judgments
a step scans, the lookups that link them (appeals, conclusions, referrals, series) and
the stubs left unreached.

A scan of judgments comes in key order, so a run reads them in the same order every time;
a lookup per value of a list in the order of that list, then by key.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from psycopg.types.json import Json

from lawgraph.config.constants import (
    RELATION_ANSWERS,
    SOURCE_CJEU,
    SOURCE_ECHR,
    SOURCE_RECHTSPRAAK,
)
from lawgraph.core.batching import chunked
from lawgraph.core.ecli import LJN_ECLI
from lawgraph.core.judgment_metadata import (
    CONCLUSION_ONLY_COURTS,
    DOCUMENT_TYPE_CONCLUSION,
    PROCEDURE_PRELIMINARY_RULING,
)
from lawgraph.db.counting import Store
from lawgraph.db.queries._chunks import CHUNK
from lawgraph.db.queries._json_sql import (
    EMPTY_ARRAY,
    array_or_empty,
    is_absent,
    is_present,
    json_length,
    truthy_or,
)
from lawgraph.db.queries.semantic import slim_sql


def _slice(value: str, length: str, element: str = "p") -> str:
    """SQL for ``SLICE(value OR [], 0, length)`` as a json array, each element *p* as
    *element* (an expression of ``p``)."""
    return f"""coalesce((
        SELECT json_agg({element} ORDER BY n)
        FROM json_array_elements({array_or_empty(value)}) WITH ORDINALITY AS s(p, n)
        WHERE n <= {length}
    ), '[]'::json)"""


# ``judgment_metadata.document_type == @conclusion OR court_code IN @conclusion_courts``
_IS_CONCLUSION = """(
    lg_str(j.props -> 'judgment_metadata' -> 'document_type') IS NOT DISTINCT FROM
        %(conclusion)s
    OR coalesce(j.court_code = ANY(%(conclusion_courts)s::text[]), false)
)"""


def _conclusion_params() -> dict[str, Any]:
    return {
        "conclusion": DOCUMENT_TYPE_CONCLUSION,
        "conclusion_courts": sorted(CONCLUSION_ONLY_COURTS),
    }


# The judgments whose paragraphs ``semantic rechtspraak`` reads for the articles they cite:
# those of the Rechtspraak and of the courts of the Union, which cite as Dutch courts do.
CITING_SOURCES = (SOURCE_RECHTSPRAAK, SOURCE_CJEU)


def judgment_paragraphs(
    store: Store,
    *,
    eclis: list[str] | None,
    batch_size: int,
    after: str | None = None,
    limit: int | None = None,
) -> Iterator[dict[str, Any]]:
    """``{ecli, date, paragraphs, footnotes, unresolved_citations, law_references}`` (as a slim document) of every
    judgment of ``CITING_SOURCES`` in key order, only those of *eclis* when it is given; a
    slice: past the key *after*, *limit* of them."""
    recent = "AND j.ecli = ANY(%(eclis)s::text[])" if eclis is not None else ""
    past = "AND j.key > %(after)s" if after else ""
    sql = f"""
        SELECT {
        slim_sql(
            "j",
            "ecli",
            "date",
            "paragraphs",
            "footnotes",
            "unresolved_citations",
            "law_references",
        )
    }
        FROM judgments j
        WHERE j.source = ANY(%(sources)s::text[]) {recent} {past}
        ORDER BY j.key
        LIMIT %(limit)s
        """
    return store.query(
        sql,
        {
            "sources": list(CITING_SOURCES),
            "eclis": eclis,
            "after": after,
            "limit": limit,
        },
        batch_size=batch_size,
    )


def count_citing_judgments(store: Store) -> int | None:
    """How many judgments of ``CITING_SOURCES`` the graph holds, from the index."""
    rows = store.query(
        "SELECT count(*)::int FROM judgments WHERE source = ANY(%(sources)s::text[])",
        {"sources": list(CITING_SOURCES)},
    )
    count = next(iter(rows), None)
    return count if isinstance(count, int) else None


def judgment_ids_by_ecli(store: Store, eclis: list[str]) -> Iterator[dict[str, Any]]:
    """``{ecli, id}`` of the judgments with these *eclis*."""
    return store.query(
        "SELECT ecli, id FROM judgments WHERE ecli = ANY(%(eclis)s::text[]) ORDER BY key",
        {"eclis": eclis},
    )


def eclis_with_an_ljn(store: Store) -> Iterator[str]:
    """The ECLIs of the judgments in the graph whose number is an LJN (published before
    2013), from the index on ``ecli``."""
    return store.query(f"SELECT ecli FROM judgments WHERE ecli ~ '{LJN_ECLI}'")


def judgments_with_related_eclis(
    store: Store, *, eclis: list[str] | None = None
) -> Iterator[dict[str, Any]]:
    """``{j_id, ecli, date, case_number, case_number_keys, procedure_type,
    related_eclis, later_eclis}`` of every judgment that names an earlier or a later one,
    only those of *eclis* when it is given."""
    related = "j.props -> 'related_eclis'"
    later = "j.props -> 'later_eclis'"
    sql = f"""
        SELECT j.id AS j_id,
               j.props -> 'ecli' AS ecli,
               j.props -> 'date_eff' AS date,
               j.props -> 'case_number' AS case_number,
               {truthy_or("j.props -> 'case_number_keys'", EMPTY_ARRAY)} AS case_number_keys,
               j.props -> 'judgment_metadata' -> 'type' AS procedure_type,
               {truthy_or(related, EMPTY_ARRAY)} AS related_eclis,
               {truthy_or(later, EMPTY_ARRAY)} AS later_eclis
        FROM judgments j
        WHERE ({json_length(related)} > 0 OR {json_length(later)} > 0) {_of_eclis(eclis)}
        ORDER BY j.key
        """
    return store.query(sql, {"eclis": eclis})


def _of_eclis(eclis: list[str] | None) -> str:
    """SQL: only the judgments of ``%(eclis)s`` (the index on ``ecli``); nothing without."""
    return "AND j.ecli = ANY(%(eclis)s::text[])" if eclis is not None else ""


def judgment_instances(store: Store, eclis: list[str]) -> Iterator[dict[str, Any]]:
    """``{ecli, id, date, case_number, case_number_keys, procedure, is_conclusion}`` of the
    judgments with these *eclis* (``core.appeals.Instance``)."""
    sql = f"""
        SELECT j.props -> 'ecli' AS ecli,
               j.id,
               j.props -> 'date_eff' AS date,
               j.props -> 'case_number' AS case_number,
               {truthy_or("j.props -> 'case_number_keys'", EMPTY_ARRAY)} AS case_number_keys,
               j.props -> 'judgment_metadata' -> 'type' AS procedure,
               {_IS_CONCLUSION} AS is_conclusion
        FROM judgments j
        WHERE j.ecli = ANY(%(eclis)s::text[])
        ORDER BY j.key
        """
    return store.query(sql, {"eclis": eclis, **_conclusion_params()})


def appeals_to_read(
    store: Store, *, procedure: str, paragraphs: int, eclis: list[str] | None = None
) -> Iterator[dict[str, Any]]:
    """``{key, j_id, ecli, read, paragraphs, unresolved_appeal_targets}`` of the appeals
    whose metadata names no earlier instance (``read``: *procedure*, a regular expression of
    PostgreSQL, matches their ``judgment_metadata.type``, case-insensitive), with their
    first *paragraphs* paragraphs; and of the judgments that carry unresolved appeal
    targets, so that those no longer read lose them. Only those of *eclis* when it is
    given."""
    targets = "j.props -> 'unresolved_appeal_targets'"
    texts = _slice(
        "props -> 'paragraphs'",
        "%(paragraphs)s",
        "json_build_object('text', p -> 'text')",
    )
    sql = f"""
        SELECT key, j_id, ecli, read,
               CASE WHEN read THEN {texts} ELSE '[]'::json END AS paragraphs,
               unresolved_appeal_targets
        FROM (
            SELECT j.key, j.id AS j_id, j.props, j.props -> 'ecli' AS ecli,
                   ({json_length("j.props -> 'related_eclis'")} = 0
                    AND coalesce(lg_str(j.props -> 'judgment_metadata' -> 'type'), '')
                        ~* %(procedure)s) AS read,
                   {targets} AS unresolved_appeal_targets,
                   {is_present(targets)} AS has_targets
            FROM judgments j
            WHERE j.source = %(source)s {_of_eclis(eclis)}
        ) j
        WHERE read OR has_targets
        ORDER BY key
        """
    return store.query(
        sql,
        {
            "source": SOURCE_RECHTSPRAAK,
            "procedure": procedure,
            "paragraphs": paragraphs,
            "eclis": eclis,
        },
    )


def conclusion_rows(store: Store) -> Iterator[dict[str, Any]]:
    """``{ecli, court_code, date, case_number, is_conclusion, conclusion_eclis,
    case_number_keys}`` of every conclusion and of every judgment that names its
    conclusion."""
    named = "j.props -> 'conclusion_eclis'"
    sql = f"""
        SELECT ecli, court_code, date, case_number, is_conclusion, conclusion_eclis,
               case_number_keys
        FROM (
            SELECT j.key,
                   j.props -> 'ecli' AS ecli,
                   j.props -> 'court_code' AS court_code,
                   j.props -> 'date_eff' AS date,
                   j.props -> 'case_number' AS case_number,
                   {_IS_CONCLUSION} AS is_conclusion,
                   {truthy_or(named, EMPTY_ARRAY)} AS conclusion_eclis,
                   {truthy_or("j.props -> 'case_number_keys'", EMPTY_ARRAY)} AS case_number_keys,
                   {json_length(named)} AS named
            FROM judgments j
            WHERE j.source = %(source)s
        ) j
        WHERE is_conclusion OR named > 0
        ORDER BY key
        """
    return store.query(sql, {"source": SOURCE_RECHTSPRAAK, **_conclusion_params()})


def judgments_by_case_keys(store: Store, keys: list[str]) -> Iterator[dict[str, Any]]:
    """``{key, ecli, court_code, date, is_conclusion}`` of the judgments with one of these
    case number *keys* (``core.case_numbers.case_number_keys``), one row per key they carry:
    in the order of *keys*, then by judgment key."""
    sql = f"""
        SELECT k.key,
               j.props -> 'ecli' AS ecli,
               j.props -> 'court_code' AS court_code,
               j.props -> 'date_eff' AS date,
               {_IS_CONCLUSION} AS is_conclusion
        FROM unnest(%(keys)s::text[]) WITH ORDINALITY AS k(key, n)
        JOIN judgments j ON j.case_number_keys @> ARRAY[k.key]
        ORDER BY k.n, j.key
        """
    return store.query(sql, {"keys": keys, **_conclusion_params()})


def judgments_on_dates(store: Store, dates: list[str]) -> Iterator[dict[str, Any]]:
    """``{ecli, date, case_number}`` of the judgments of these *dates*, conclusions among
    them (``conclusions_among`` tells them apart). From the columns and ``lg_judgment_light``:
    the dates an appeal or a referral names cover nearly every court day, and the props of
    every judgment of them would be its text."""
    sql = """
        SELECT j.ecli, j.date_eff AS date, l.props -> 'case_number' AS case_number
        FROM judgments j
        JOIN lg_judgment_light l ON l.id = j.id
        WHERE j.date_eff = ANY(%(dates)s::text[]) AND j.ecli IS NOT NULL
        ORDER BY j.key
        """
    return store.query(sql, {"dates": dates})


def conclusions_among(store: Store, eclis: list[str]) -> set[str]:
    """The conclusions (of an advocate-general) among the judgments of *eclis*, upper case:
    by their ``document_type`` or their court. Read for the few that matched."""
    sql = f"""
        SELECT upper(j.ecli) AS ecli FROM judgments j
        WHERE j.ecli = ANY(%(eclis)s::text[]) AND {_IS_CONCLUSION}
        """
    return {
        str(ecli)
        for ecli in store.query(sql, {"eclis": eclis, **_conclusion_params()})
        if ecli
    }


def court_decisions_between(
    store: Store, spans: list[dict[str, str]]
) -> Iterator[dict[str, Any]]:
    """``{court_code, ecli, date, case_number}`` of the decisions (not conclusions) of the
    court of each span (``{court_code, start, end}``; a court code of None is a judgment
    without one) dated from its start to its end; each distinct row once, where it first
    comes (in the order of *spans*, then by key)."""
    distinct = (
        "coalesce(court_code::jsonb, 'null'), coalesce(ecli::jsonb, 'null'), date,"
        " coalesce(case_number::jsonb, 'null')"
    )
    # The judgments of a span's court, or of none when it names none: two branches, so
    # the first finds them through the index on (court_code, date_eff). One OR of both
    # read every judgment of the span's years, of every court (and its props), per span.
    # A row both branches find is the same row; DISTINCT ON keeps it once.
    found = """
        SELECT s.n, j.key,
               j.props -> 'court_code' AS court_code,
               j.props -> 'ecli' AS ecli,
               j.date_eff AS date,
               j.props -> 'case_number' AS case_number,
               j.props -> 'judgment_metadata' -> 'document_type' AS document_type
        FROM json_array_elements(%(spans)s::json) WITH ORDINALITY AS s(span, n)
        JOIN judgments j ON {court}
        WHERE j.date_eff >= lg_str(s.span -> 'start')
          AND j.date_eff <= lg_str(s.span -> 'end')
    """
    of_its_court = "j.court_code = lg_str(s.span -> 'court_code')"
    # (a condition on the span alone: it leaves out the spans that name a court before
    # any judgment is read)
    of_no_court = (
        is_absent("s.span -> 'court_code'")
        + " AND "
        + is_absent("j.props -> 'court_code'")
    )
    sql = f"""
        SELECT court_code, ecli, date, case_number
        FROM (
            SELECT DISTINCT ON ({distinct}) n, key, court_code, ecli, date, case_number
            FROM (
                {found.format(court=of_its_court)}
                UNION ALL
                {found.format(court=of_no_court)}
            ) found
            WHERE lg_str(document_type) IS DISTINCT FROM %(conclusion)s
            ORDER BY {distinct}, n, key
        ) once
        ORDER BY n, key
        """
    return store.query(
        sql, {"spans": Json(spans), "conclusion": DOCUMENT_TYPE_CONCLUSION}
    )


def preliminary_rulings(
    store: Store, *, paragraphs: int, eclis: list[str] | None = None
) -> Iterator[dict[str, Any]]:
    """``{ecli, related_eclis, paragraphs}`` of every preliminary ruling, with its first
    *paragraphs* paragraphs (where it says who asked its questions); only those of *eclis*
    when it is given."""
    sql = f"""
        SELECT j.props -> 'ecli' AS ecli,
               {truthy_or("j.props -> 'related_eclis'", EMPTY_ARRAY)} AS related_eclis,
               {_slice("j.props -> 'paragraphs'", "%(paragraphs)s")} AS paragraphs
        FROM judgments j
        WHERE j.procedure = %(procedure)s {_of_eclis(eclis)}
        ORDER BY j.key
        """
    return store.query(
        sql,
        {
            "procedure": PROCEDURE_PRELIMINARY_RULING,
            "paragraphs": paragraphs,
            "eclis": eclis,
        },
    )


def unanswered_ruling_eclis(store: Store) -> Iterator[str]:
    """The ECLIs of the preliminary rulings without an ANSWERS edge, by ECLI."""
    return store.query(
        """
        SELECT j.ecli FROM judgments j
        WHERE j.procedure = %(procedure)s AND j.ecli IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM edges e WHERE e.from_id = j.id AND e.relation = %(answers)s
          )
        ORDER BY j.ecli NULLS FIRST
        """,
        {"procedure": PROCEDURE_PRELIMINARY_RULING, "answers": RELATION_ANSWERS},
    )


def generic_summaries(store: Store, *, min_dates: int) -> Iterator[str]:
    """The MD5 (``core.judgment_series.summary_fingerprint``) of every Rechtspraak summary
    written on at least *min_dates* distinct dates (a missing date counts as one), in
    order: templates, not summaries."""
    sql = f"""
        SELECT md5(j.props -> 'summary' #>> '{{}}') AS fingerprint
        FROM judgments j
        WHERE j.source = %(source)s AND {is_present("j.props -> 'summary'")}
        GROUP BY fingerprint
        HAVING count(DISTINCT coalesce((j.props -> 'date_eff')::jsonb, 'null'))
            >= %(min_dates)s
        ORDER BY fingerprint
        """
    return store.query(sql, {"source": SOURCE_RECHTSPRAAK, "min_dates": min_dates})


# The judgments of one court on one day, read through the index that `/api/stats/coverage`
# counts from (``db/schema.py``): every field of its prefix is fixed.
_COURT_DAY_FILTER = "j.stub IS FALSE AND j.source = %(source)s"


def judgment_court_days(
    store: Store, *, eclis: list[str] | None = None
) -> Iterator[dict[str, Any]]:
    """``{court_code, date, tier, courts}`` of every day on which a court gave two or more
    Rechtspraak judgments, or, with *eclis*, of the days of those judgments; by court and
    day. ``courts`` holds each court name once (None too), where it first comes in key
    order."""
    of_eclis = "AND j.ecli = ANY(%(eclis)s::text[])" if eclis is not None else ""
    sql = f"""
        SELECT j.court_code, j.date_eff AS date, max(j.tier) AS tier,
               lg_array_union(array_agg(j.court ORDER BY j.key), '{{}}') AS courts
        FROM judgments j
        WHERE {_COURT_DAY_FILTER} {of_eclis}
          AND j.court_code IS NOT NULL AND j.date_eff IS NOT NULL
        GROUP BY j.court_code, j.date_eff
        HAVING %(eclis_given)s OR count(*) > 1
        ORDER BY j.court_code, j.date_eff
        """
    return store.query(
        sql,
        {
            "source": SOURCE_RECHTSPRAAK,
            "eclis": eclis,
            "eclis_given": eclis is not None,
        },
    )


def judgments_in_series(store: Store) -> Iterator[str]:
    """The ECLIs of the judgments that carry a ``series_id``."""
    sql = f"""
        SELECT j.props -> 'ecli' FROM judgments j
        WHERE {is_present("j.props -> 'series_id'")}
        ORDER BY j.key
        """
    return store.query(sql)


def replaced_judgments(store: Store) -> Iterator[dict[str, Any]]:
    """``{id, key, ecli, replaced_by, same_as}`` of the judgments a later publication
    replaces (``props.replaced_by``) and of those ``SAME_AS`` another now."""
    sql = f"""
        SELECT j.id, j.key,
               j.props -> 'ecli' AS ecli,
               j.props -> 'replaced_by' AS replaced_by,
               j.props -> 'same_as' AS same_as
        FROM judgments j
        WHERE {is_present("j.props -> 'replaced_by'")} OR {is_present("j.props -> 'same_as'")}
        ORDER BY j.key
        """
    return store.query(sql)


def loaded_judgment_ids(store: Store, eclis: list[str]) -> Iterator[dict[str, Any]]:
    """``{ecli, id}`` of the judgments with these *eclis* that are loaded (no stub)."""
    return store.query(
        """
        SELECT ecli, id FROM judgments
        WHERE ecli = ANY(%(eclis)s::text[]) AND stub IS NOT TRUE
        ORDER BY key
        """,
        {"eclis": eclis},
    )


def judgments_of_court_day(
    store: Store,
    *,
    court_code: str,
    date: str,
    tier: str | None,
    courts: list[str | None],
    batch_size: int,
) -> Iterator[dict[str, Any]]:
    """``{key, ecli, text, summary, document_type, case_number_keys, series_id,
    series_size}`` of the Rechtspraak judgments of one court on one day. A *tier* of None
    is a judgment without one, as is a None in *courts*."""
    sql = f"""
        SELECT j.key,
               j.props -> 'ecli' AS ecli,
               j.props -> 'text' AS text,
               j.props -> 'summary' AS summary,
               j.props -> 'judgment_metadata' -> 'document_type' AS document_type,
               {truthy_or("j.props -> 'case_number_keys'", EMPTY_ARRAY)} AS case_number_keys,
               j.props -> 'series_id' AS series_id,
               j.props -> 'series_size' AS series_size
        FROM judgments j
        WHERE {_COURT_DAY_FILTER}
          AND (j.tier = %(tier)s
               OR (%(tier)s::text IS NULL AND {is_absent("j.props -> 'tier'")}))
          AND j.court_code = %(court_code)s
          AND (j.court = ANY(%(courts)s::text[])
               OR (array_position(%(courts)s::text[], NULL) IS NOT NULL
                   AND {is_absent("j.props -> 'court'")}))
          AND j.date_eff = %(date)s
        ORDER BY j.key
        """
    params = {
        "source": SOURCE_RECHTSPRAAK,
        "court_code": court_code,
        "date": date,
        "tier": tier,
        "courts": courts,
    }
    return store.query(sql, params, batch_size=batch_size)


def echr_judgments(store: Store) -> Iterator[dict[str, Any]]:
    """``{j_id, j_key, articles, conclusion}`` of the ECHR judgments that cite an article
    or have a conclusion."""
    sql = f"""
        SELECT j.id AS j_id, j.key AS j_key,
               j.props -> 'articles' AS articles,
               j.props -> 'conclusion' AS conclusion
        FROM judgments j
        WHERE j.source = %(source)s
          AND ({is_present("j.props -> 'articles'")}
               OR {is_present("j.props -> 'conclusion'")})
        ORDER BY j.key
        """
    return store.query(sql, {"source": SOURCE_ECHR})


def procedural_neighbors(
    store: Store, ids: list[str], relations: list[str]
) -> Iterator[list[str]]:
    """``[id, other]`` for every edge of *relations* between a node of *ids* and another,
    either way: in the order of *ids*, then by edge key."""
    sql = """
        SELECT ARRAY[i.id, x.other]
        FROM unnest(%(ids)s::text[]) WITH ORDINALITY AS i(id, n)
        CROSS JOIN LATERAL (
            SELECT e.key, e.to_id AS other FROM edges e
            WHERE e.from_id = i.id AND e.relation = ANY(%(relations)s::text[])
            UNION ALL
            SELECT e.key, e.from_id FROM edges e
            WHERE e.to_id = i.id AND e.from_id <> i.id
              AND e.relation = ANY(%(relations)s::text[])
        ) x
        ORDER BY i.n, x.key
        """
    for chunk in chunked(ids, CHUNK):
        yield from store.query(sql, {"ids": chunk, "relations": relations})


def remove_unreached_judgment_stubs(store: Store) -> int:
    """Remove the stub judgments no edge reaches or leaves any more: a stub stands in for a
    judgment something links, and one nothing links is left from an earlier run. How many
    went."""
    rows = store.execute(
        """
        DELETE FROM judgments j
        WHERE j.stub IS TRUE
          AND NOT EXISTS (SELECT 1 FROM edges e WHERE e.to_id = j.id)
          AND NOT EXISTS (SELECT 1 FROM edges e WHERE e.from_id = j.id)
        RETURNING 1
        """
    )
    return len(rows)


def judgments_naming_related_cases(
    store: Store, *, eclis: list[str] | None = None
) -> Iterator[dict[str, Any]]:
    """``{id, ecli, court_code, summary}`` of the judgments whose summary has a sentence that
    names connected cases ("Samenhang met", "Zie ook", "Zie tevens"), by key; only those of
    *eclis* when it is given."""
    return store.query(
        f"""
        SELECT j.id, j.props -> 'ecli' AS ecli, j.props -> 'court_code' AS court_code,
               j.props ->> 'summary' AS summary
        FROM judgments j
        WHERE j.props ->> 'summary' ~* '(samenhang[[:space:]]+met|zie[[:space:]]+(ook|tevens))'
          {_of_eclis(eclis)}
        ORDER BY j.key
        """,
        {"eclis": eclis},
    )


def echr_decisions(store: Store) -> Iterator[dict[str, Any]]:
    """``{id, appno, date}`` of every ECHR decision, one per decision: not a language
    version that is ``SAME_AS`` another (``semantic echr-versions``). Columns only."""
    sql = """
        SELECT j.id, j.appno, j.date_eff AS date
        FROM judgments j
        WHERE j.source = %(source)s AND coalesce(j.appno, '') <> '' AND j.same_as IS NULL
        ORDER BY j.key
        """
    return store.query(sql, {"source": SOURCE_ECHR})


def echr_texts(store: Store) -> Iterator[dict[str, Any]]:
    """``{j_id, appno, text}`` of the ECHR judgments with a text (their DOCX, English or
    French), one per decision."""
    sql = """
        SELECT j.id AS j_id, j.appno, j.props -> 'text' AS text
        FROM judgments j
        WHERE j.source = %(source)s AND j.same_as IS NULL
          AND json_typeof(j.props -> 'text') = 'string'
        ORDER BY j.key
        """
    return store.query(sql, {"source": SOURCE_ECHR})


def echr_versions(store: Store) -> Iterator[dict[str, Any]]:
    """``{id, key, appno, date, item_id, language, same_as}`` of the ECHR decisions without
    an ECLI and with an appno: HUDOC holds one per language, each a node of its own (a
    decision with an ECLI is one node already)."""
    sql = """
        SELECT j.id, j.key, j.appno, j.date_eff AS date,
               lg_str(j.props -> 'external_id') AS item_id,
               lg_str(j.props -> 'language') AS language,
               j.same_as
        FROM judgments j
        WHERE j.source = %(source)s AND j.ecli IS NULL AND coalesce(j.appno, '') <> ''
        ORDER BY j.key
        """
    return store.query(sql, {"source": SOURCE_ECHR})
