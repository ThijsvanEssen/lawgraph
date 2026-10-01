"""The reads of the semantic phase for the Tweede and Eerste Kamer: the papers a step scans,
the memoranda and their targets, and the signals of how a dossier ended.

A read whose order ArangoDB left open comes in the order of the keys, so a run reads the same
rows in the same order every time; a list within a row in the order of its edges' keys.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import (
    CHAMBER_EK,
    CHAMBER_TK,
    COLLECTION_ARTICLE_VERSIONS,
    COLLECTION_ARTICLES,
    COLLECTION_CASES,
    COLLECTION_DECISIONS,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_EDGES,
    COLLECTION_INSTRUMENTS,
    EXPLANATORY_KIND_MARKER,
    RELATION_ABOUT,
    RELATION_AMENDS,
    RELATION_EXPLAINS,
    RELATION_INTRODUCES,
    RELATION_LEGISLATED_IN,
    RELATION_PART_OF,
    RELATION_REPEALS,
    RELATION_SECOND_READING_OF,
    SOURCE_EERSTEKAMER,
)
from lawgraph.db._rows import node_doc
from lawgraph.db.counting import Store
from lawgraph.db.queries.semantic import (
    absent_sql,
    nonempty_sql,
    present_sql,
    slim_sql,
)

_CHANGE_RELATIONS = (RELATION_AMENDS, RELATION_INTRODUCES, RELATION_REPEALS)

# ``CONTAINS(LOWER(doc.props.kind || ""), marker)`` of the document ``d``: the kind column
# holds a string kind without reading the payload; another kind is read as its text.
_EXPLANATORY = (
    "strpos(lower(coalesce(d.kind, d.props ->> 'kind')),"
    f" '{EXPLANATORY_KIND_MARKER}') > 0"
)


def _keep(props: str, *fields: str) -> str:
    """SQL: AQL ``KEEP(props, fields)``, the fields *props* has with their keys in byte
    order (probe P1)."""
    names = ", ".join(f"'{field}'" for field in fields)
    return f"""coalesce(
        (SELECT json_object_agg(key, v ORDER BY key COLLATE "C")
         FROM json_each({props}) AS p(key, v) WHERE key IN ({names})),
        '{{}}'::json
    )"""


def _cut(alias: str, *fields: str) -> str:
    """SQL: the props of *alias* cut down to *fields* in one pass (``NULL`` without any):
    a TK document holds its whole payload, and every ``->`` on it parses it again."""
    names = ", ".join(f"'{field}'" for field in fields)
    return (
        f"(SELECT json_object_agg(j.k, j.v) FROM json_each({alias}.props) AS j(k, v)"
        f" WHERE j.k IN ({names}))"
    )


def _to_string(value: str) -> str:
    """SQL: AQL ``TO_STRING(value)`` of a json value: a string itself, a number in its
    shortest form (``37020.0`` is ``"37020"``), anything else its JSON text."""
    return (
        f"CASE json_typeof({value}) WHEN 'string' THEN ({value}) #>> '{{}}'"
        f" WHEN 'number' THEN lg_num({value})::text ELSE ({value})::text END"
    )


def _or_empty_string(value: str) -> str:
    """SQL: AQL ``value || ""`` of a json value, as jsonb to compare by value."""
    return f"(CASE WHEN lg_truthy({value}) THEN {value} ELSE '\"\"'::json END)::jsonb"


def _column_or_prop(alias: str, field: str) -> str:
    """SQL: the json value of the prop *field* of *alias*: from its generated column when
    the prop is a string, else from the props."""
    return f"coalesce(to_json({alias}.{field}), {alias}.props -> '{field}')"


_SECOND_READING_SQL = f"""
SELECT json_build_object(
    'labels', (
        SELECT coalesce(json_agg(ds.props -> 'label' ORDER BY e.key), '[]'::json)
        FROM {COLLECTION_EDGES} e
        LEFT JOIN {COLLECTION_DOSSIERS} ds ON ds.id = e.to_id
        WHERE e.from_id = m.id AND e.relation = %(part_of)s
          AND e.to_collection = '{COLLECTION_DOSSIERS}'
    ),
    'text', m.text
)
FROM (
    SELECT d.id, d.key, c.text
    FROM {COLLECTION_DOCUMENTS} d
    CROSS JOIN LATERAL (SELECT d.props -> 'text' AS text OFFSET 0) c
    WHERE '{CHAMBER_TK}' = ANY(d.labels) AND {_EXPLANATORY}
      AND {present_sql("c.text")}
      AND strpos(lower(c.text #>> '{{}}'), 'eerste lezing') > 0
) m
ORDER BY m.key
"""


def second_reading_memoranda(store: Store) -> Iterator[dict[str, Any]]:
    """``{labels, text}`` of the explanatory memoranda that speak of a first reading, with
    the labels of their dossiers: a change in the Grondwet in its second reading refers to
    the papers of the first (``core.dossier_numbers.first_reading_dossiers``)."""
    return store.query(_SECOND_READING_SQL, {"part_of": RELATION_PART_OF})


def tk_documents(store: Store, ids: list[str] | None) -> Iterator[dict[str, Any]]:
    """The whole Tweede Kamer documents, only those with an external id in *ids* when it is
    given: ``semantic tk`` scans every text prop of a paper and its API payload."""
    id_filter = ""
    if ids is not None:
        id_filter = "AND lg_str(props -> 'external_id') = ANY(%(ids)s::text[])"
    sql = f"""
        SELECT id, key, type, labels, props
        FROM {COLLECTION_DOCUMENTS}
        WHERE '{CHAMBER_TK}' = ANY(labels) {id_filter}
        ORDER BY key
        """
    return (node_doc(row) for row in store.query(sql, {"ids": ids}))


def tk_document_titles(
    store: Store, since_date: str | None
) -> Iterator[dict[str, Any]]:
    """The Tweede Kamer documents with their kind, their title and, of a paper named by its own
    subject, the title of its dossier; those of *since_date* or later when it is given."""
    # ``doc.props.date >= @since``: a string by the collation; an array or an object sorts
    # above every string in ArangoDB, so it passes too
    since_filter = ""
    if since_date is not None:
        since_filter = (
            "AND (d.date >= %(since)s OR (d.date IS NULL"
            " AND json_typeof(d.props -> 'date') IN ('array', 'object')))"
        )
    sql = f"""
        SELECT {slim_sql("d", "kind", "title", "dossier_title", "display_name")}
        FROM {COLLECTION_DOCUMENTS} d
        WHERE '{CHAMBER_TK}' = ANY(d.labels) {since_filter}
        ORDER BY d.key
        """
    return store.query(sql, {"since": since_date})


_TO_SCAN_FOR_AMENDMENTS_SQL = f"""
SELECT {slim_sql("c", "bwb_id", "text")}
FROM (
    SELECT d.id, d.key, d.type, d.labels, coalesce(p.props, '{{}}'::json) AS props
    FROM {COLLECTION_DOCUMENTS} d
    CROSS JOIN LATERAL (SELECT {_cut("d", "bwb_id", "text")} AS props OFFSET 0) p
    WHERE '{CHAMBER_TK}' = ANY(d.labels)
) c
WHERE {present_sql("c.props -> 'text'")}
  AND lg_str(c.props -> 'text') IS DISTINCT FROM ''
  AND ({present_sql("c.props -> 'bwb_id'")} OR c.id = ANY(%(amending)s::text[]))
ORDER BY c.key
"""


def tk_documents_to_scan_for_amendments(
    store: Store, amending: list[str]
) -> Iterator[dict[str, Any]]:
    """The Tweede Kamer documents with a text and a law to amend: their own ``bwb_id``, or
    their id in *amending*."""
    return store.query(_TO_SCAN_FOR_AMENDMENTS_SQL, {"amending": amending})


_AMENDED_INSTRUMENTS_SQL = f"""
SELECT e.from_id AS document_id, i.props -> 'bwb_id' AS bwb_id
FROM {COLLECTION_EDGES} e
JOIN {COLLECTION_INSTRUMENTS} i ON i.id = e.to_id
WHERE e.relation = %(relation)s
  AND e.from_collection = '{COLLECTION_DOCUMENTS}'
  AND e.to_collection = '{COLLECTION_INSTRUMENTS}'
  AND {present_sql("i.props -> 'bwb_id'")}
ORDER BY e.key
"""


def amended_instruments(store: Store) -> Iterator[dict[str, Any]]:
    """``{document_id, bwb_id}`` per AMENDS edge from a document to an instrument with a BWB
    id."""
    return store.query(_AMENDED_INSTRUMENTS_SQL, {"relation": RELATION_AMENDS})


# The dossier of a paper: the first by key of those with its number and suffix (ArangoDB
# took one of them, unsorted).
_EK_PAPERS_SQL = f"""
SELECT json_build_object(
    'document_key', c.key,
    'dossier_key', dossier.key,
    'dossier_number', c.p -> 'dossier_number',
    'dossier_suffix', c.p -> 'dossier_suffix'
)
FROM (
    SELECT d.key, p.p
    FROM {COLLECTION_DOCUMENTS} d
    CROSS JOIN LATERAL (
        SELECT {_cut("d", "dossier_number", "dossier_suffix")} AS p OFFSET 0
    ) p
    WHERE d.source = %(source)s
) c
CROSS JOIN LATERAL (
    SELECT ds.key
    FROM {COLLECTION_DOSSIERS} ds
    WHERE ds.number = {_to_string("(c.p -> 'dossier_number')")}
      AND {_or_empty_string("ds.props -> 'suffix'")}
          = {_or_empty_string("(c.p -> 'dossier_suffix')")}
    ORDER BY ds.key
    LIMIT 1
) dossier
WHERE {present_sql("c.p -> 'dossier_number'")}
ORDER BY c.key
"""


def ek_papers_in_tk_dossiers(store: Store) -> Iterator[dict[str, Any]]:
    """``{document_key, dossier_key, dossier_number, dossier_suffix}`` of the Eerste Kamer
    papers whose dossier number is a Tweede Kamer dossier in the graph."""
    return store.query(_EK_PAPERS_SQL, {"source": SOURCE_EERSTEKAMER})


# Per explanatory document ``d``: ``o.own_dossiers``, the dossiers it is PART_OF;
# ``p.paper_dossiers``, those and the dossiers whose second reading they are (a first
# reading explains what its second reading made law); ``l.legislated``, the instruments
# LEGISLATED_IN one of them. Each in the order of the edges, every value once.
_LEGISLATED = f"""
    CROSS JOIN LATERAL (
        SELECT ARRAY(
            SELECT e.to_id
            FROM {COLLECTION_EDGES} e
            WHERE e.from_id = d.id AND e.relation = %(part_of)s
              AND e.to_collection = '{COLLECTION_DOSSIERS}'
            ORDER BY e.key
        ) AS own_dossiers
    ) o
    CROSS JOIN LATERAL (
        SELECT lg_array_union(o.own_dossiers, ARRAY(
            SELECT e.from_id
            FROM unnest(o.own_dossiers) WITH ORDINALITY AS u(dossier, n)
            JOIN {COLLECTION_EDGES} e
              ON e.to_id = u.dossier AND e.relation = %(second_reading_of)s
            ORDER BY u.n, e.key
        )) AS paper_dossiers
    ) p
    CROSS JOIN LATERAL (
        SELECT lg_array_union(ARRAY(
            SELECT e.from_id
            FROM unnest(p.paper_dossiers) WITH ORDINALITY AS u(dossier, n)
            JOIN {COLLECTION_EDGES} e
              ON e.to_id = u.dossier AND e.relation = %(legislated_in)s
             AND e.from_collection = '{COLLECTION_INSTRUMENTS}'
            ORDER BY u.n, e.key
        ), '{{}}') AS legislated
    ) l"""

# The edges of a change from the instruments of ``l.legislated`` to an article.
_CHANGE_EDGES = f"""
    FROM unnest(l.legislated) WITH ORDINALITY AS u(instrument, n)
    JOIN {COLLECTION_EDGES} e
      ON e.from_id = u.instrument AND e.relation = ANY(%(change_relations)s::text[])
     AND e.to_collection = '{COLLECTION_ARTICLES}'"""

_VERSION = "e.doc -> 'meta' -> 'article_version'"

# One pass: per explanatory document, the nodes it explains.
#
# Those are the article versions (or articles, or the instrument itself) that the instrument
# legislated in the document's dossier introduced or changed, less what an edge of the
# sections linker explains already. (ArangoDB's MINUS gave them in an order of its own; here
# they keep the order of the edges.)
MEMORANDUM_TARGETS_SQL = f"""
SELECT json_build_object('document', t.id, 'targets', to_json(ARRAY(
    SELECT u.target
    FROM unnest(CASE WHEN cardinality(t.changed) > 0 THEN t.changed ELSE t.legislated END)
         WITH ORDINALITY AS u(target, n)
    WHERE u.target <> ALL(t.upgraded)
    ORDER BY u.n
)))
FROM (
    SELECT d.id, d.key, l.legislated,
           ARRAY(
               SELECT e.to_id
               FROM {COLLECTION_EDGES} e
               WHERE e.from_id = d.id AND e.relation = %(explains)s
                 AND e.source = %(sections_source)s
           ) AS upgraded,
           lg_array_union(ARRAY(
               SELECT CASE WHEN {absent_sql(_VERSION)} THEN e.to_id
                           ELSE '{COLLECTION_ARTICLE_VERSIONS}/' || {_to_string(_VERSION)}
                      END
               {_CHANGE_EDGES}
               ORDER BY u.n, e.key
           ), '{{}}') AS changed
    FROM {COLLECTION_DOCUMENTS} d
    {_LEGISLATED}
    WHERE {_EXPLANATORY} AND cardinality(l.legislated) > 0
) t
ORDER BY t.key
"""


def memorandum_targets(store: Store, *, sections_source: str) -> Iterator[Any]:
    """``{document, targets}`` per explanatory memorandum: what the instrument legislated in
    its dossier (or in the second reading of its dossier) changed, less what an edge of
    *sections_source* already explains."""
    params: dict[str, Any] = {
        "part_of": RELATION_PART_OF,
        "legislated_in": RELATION_LEGISLATED_IN,
        "second_reading_of": RELATION_SECOND_READING_OF,
        "explains": RELATION_EXPLAINS,
        "sections_source": sections_source,
        "change_relations": list(_CHANGE_RELATIONS),
    }
    return store.query(MEMORANDUM_TARGETS_SQL, params)


# One pass: per memorandum with sections, what its dossier legislated and changed.
#
# A budget paper explains policy articles and a paper without article headings has no sections
# to read; a dossier that legislated nothing has nothing to link to. ``own``: the BWB ids of
# the instruments legislated; ``changes``: every distinct change of an article with a BWB id
# and a number, in the order of the edges; ``laws``: the instruments of those BWB ids, by key.
_MEMORANDA_WITH_SECTIONS_SQL = f"""
SELECT json_build_object(
    'document', d.id,
    'text', d.p -> 'text',
    'sections', d.p -> 'sections',
    'own', own.own,
    'changes', ch.changes,
    'laws', laws.laws
)
FROM (
    SELECT d.id, d.key, c.p
    FROM {COLLECTION_DOCUMENTS} d
    CROSS JOIN LATERAL (
        SELECT {_cut("d", "budget", "structure_quality", "text", "sections")} AS p
        OFFSET 0
    ) c
    WHERE {_EXPLANATORY}
      AND lg_bool(c.p -> 'budget') IS DISTINCT FROM true
      AND lg_str(c.p -> 'structure_quality') = ANY(%(qualities)s::text[])
      AND {present_sql("c.p -> 'text'")}
) d
{_LEGISLATED}
CROSS JOIN LATERAL (
    SELECT coalesce(json_agg(x.bwb_id ORDER BY x.n), '[]'::json) AS own
    FROM (
        SELECT u.n, {_column_or_prop("i", "bwb_id")} AS bwb_id
        FROM unnest(l.legislated) WITH ORDINALITY AS u(instrument, n)
        JOIN {COLLECTION_INSTRUMENTS} i ON i.id = u.instrument
    ) x
    WHERE {present_sql("x.bwb_id")}
) own
CROSS JOIN LATERAL (
    SELECT coalesce(json_agg(g.change ORDER BY g.ord), '[]'::json) AS changes
    FROM (
        -- RETURN DISTINCT: equal changes once, where the first of them is
        SELECT (array_agg(x.change ORDER BY x.ord))[1] AS change, min(x.ord) AS ord
        FROM (
            SELECT row_number() OVER (ORDER BY u.n, e.key) AS ord,
                   json_build_object(
                       'bwb_id', a.bwb_id,
                       'number', a.number,
                       'article', e.to_id,
                       'version', {_VERSION},
                       'relation', e.relation
                   ) AS change
            {_CHANGE_EDGES}
            CROSS JOIN LATERAL (
                SELECT {_column_or_prop("art", "bwb_id")} AS bwb_id,
                       {_column_or_prop("art", "article_number")} AS number
                FROM {COLLECTION_ARTICLES} art
                WHERE art.id = e.to_id
            ) a
            WHERE {present_sql("a.bwb_id")} AND {present_sql("a.number")}
        ) x
        GROUP BY x.change::jsonb
    ) g
) ch
CROSS JOIN LATERAL (
    SELECT ARRAY(
        SELECT json_array_elements(own.own)::jsonb
        UNION ALL
        SELECT (json_array_elements(ch.changes) -> 'bwb_id')::jsonb
    ) AS wanted
) w
CROSS JOIN LATERAL (
    SELECT coalesce(json_agg(json_build_object(
        'bwb_id', {_column_or_prop("law", "bwb_id")},
        'names', json_build_array(law.props -> 'title', law.props -> 'citation_title'),
        'codes', json_build_array(law.props -> 'short_title')
    ) ORDER BY law.key), '[]'::json) AS laws
    FROM (
        SELECT i.key, i.bwb_id, i.props
        FROM {COLLECTION_INSTRUMENTS} i
        WHERE i.bwb_id = ANY(ARRAY(
            SELECT v #>> '{{}}' FROM unnest(w.wanted) AS v WHERE jsonb_typeof(v) = 'string'
        ))
        UNION ALL
        -- a BWB id of another type matches by value: never so in the sources, so the
        -- instruments are only read when one is wanted
        SELECT i.key, i.bwb_id, i.props
        FROM {COLLECTION_INSTRUMENTS} i
        WHERE EXISTS (
            SELECT 1 FROM unnest(w.wanted) AS v WHERE jsonb_typeof(v) <> 'string'
        )
          AND i.bwb_id IS NULL AND (i.props -> 'bwb_id')::jsonb = ANY(w.wanted)
    ) law
) laws
WHERE cardinality(l.legislated) > 0
ORDER BY d.key
"""


def memoranda_with_sections(
    store: Store, *, qualities: list[str], batch_size: int
) -> Iterator[dict[str, Any]]:
    """Per memorandum of a structure quality in *qualities*: its text and sections, the
    laws its dossier legislated (``own``), the articles they changed and the names of the
    laws involved. The dossier of a first reading of a change in the Grondwet counts with
    the dossier of its second reading, in which the change was made law."""
    params: dict[str, Any] = {
        "qualities": qualities,
        "part_of": RELATION_PART_OF,
        "legislated_in": RELATION_LEGISLATED_IN,
        "second_reading_of": RELATION_SECOND_READING_OF,
        "change_relations": list(_CHANGE_RELATIONS),
    }
    return store.query(_MEMORANDA_WITH_SECTIONS_SQL, params, batch_size=batch_size)


def dossier_ids(store: Store) -> Iterator[str]:
    """The ``_id`` of every dossier."""
    return store.query(f"SELECT id FROM {COLLECTION_DOSSIERS} ORDER BY key")


_DOSSIER_PROPS = _keep(
    "ds.props",
    "closed",
    "closed_on",
    "outcome",
    "tk_decision",
    "ek_outcome",
    "ek_rejected",
    "kind",
)
_BILL_DECISION_PROPS = _keep(
    "dc.props", "date", "passed", "decision_kind", "decision_text"
)
_EK_VOTE_PROPS = _keep(
    "dc.props",
    "date",
    "result",
    "method",
    "source_url",
    "retrieved_on",
    "bill_decision",
    "kind",
)

# Per dossier what says how it ended: the instruments legislated in it, the decisions on
# its bill, and the votes of the Eerste Kamer about it; and what it holds now. A decision
# comes once per edge to the dossier; the caller keeps the first of equal decisions and the
# first vote of a day: by id, it is the same one every time.
_DOSSIER_OUTCOME_SIGNALS_SQL = f"""
SELECT json_build_object(
    'key', ds.key,
    'props', {_DOSSIER_PROPS},
    'publications', (
        SELECT coalesce(json_agg(json_build_object(
            'date_published', i.props -> 'date_published',
            'date_signed', i.props -> 'date_signed'
        ) ORDER BY e.key), '[]'::json)
        FROM {COLLECTION_EDGES} e
        JOIN {COLLECTION_INSTRUMENTS} i ON i.id = e.from_id
        WHERE e.to_id = ds.id AND e.relation = %(legislated_in)s
          AND e.from_collection = '{COLLECTION_INSTRUMENTS}'
    ),
    'bill_decisions', (
        SELECT coalesce(json_agg(
            {_BILL_DECISION_PROPS}
            ORDER BY dc.id, e.key
        ), '[]'::json)
        FROM {COLLECTION_EDGES} e
        JOIN {COLLECTION_DECISIONS} dc ON dc.id = e.from_id
        WHERE e.to_id = ds.id AND e.relation = %(about)s
          AND e.from_collection = '{COLLECTION_DECISIONS}'
          AND lg_str(dc.props -> 'primary_case_kind') = ANY(%(bill_case_kinds)s::text[])
    ),
    'ek_votes', (
        SELECT coalesce(json_agg(lg_merge(
            json_build_object('id', dc.id),
            {_EK_VOTE_PROPS}
        ) ORDER BY dc.id, e.key), '[]'::json)
        FROM {COLLECTION_EDGES} e
        JOIN {COLLECTION_DECISIONS} dc ON dc.id = e.from_id
        WHERE e.to_id = ds.id AND e.relation = %(about)s
          AND e.from_collection = '{COLLECTION_DECISIONS}'
          AND lg_str(dc.props -> 'chamber') = '{CHAMBER_EK}'
    )
)
FROM unnest(%(dossier_ids)s::text[]) WITH ORDINALITY AS a(dossier_id, ord)
JOIN {COLLECTION_DOSSIERS} ds ON ds.id = a.dossier_id
ORDER BY a.ord
"""


def dossier_outcome_signals(
    store: Store, dossier_ids: list[str], *, bill_case_kinds: list[str]
) -> Iterator[dict[str, Any]]:
    """``{key, props, publications, bill_decisions, ek_votes}`` per dossier of
    *dossier_ids*: the instruments ``LEGISLATED_IN`` it, the decisions on a case of one of
    *bill_case_kinds*, the votes of the Eerste Kamer about it, and the outcome props it
    holds now."""
    params: dict[str, Any] = {
        "dossier_ids": dossier_ids,
        "legislated_in": RELATION_LEGISLATED_IN,
        "about": RELATION_ABOUT,
        "bill_case_kinds": bill_case_kinds,
    }
    return store.query(_DOSSIER_OUTCOME_SIGNALS_SQL, params)


def dossier_refs(store: Store) -> Iterator[dict[str, Any]]:
    """``{label, number, suffix, title}`` of every dossier: what the relation rules read."""
    return store.query(
        f"""
        SELECT {_keep("props", "label", "number", "suffix", "title")}
        FROM {COLLECTION_DOSSIERS}
        ORDER BY key
        """
    )


_RELATED_CASES_SQL = f"""
SELECT json_build_object(
    'id', props -> 'external_id',
    'kind', props -> 'kind',
    'dossier_numbers', props -> 'dossier_numbers',
    'related_cases', props -> 'related_cases'
)
FROM {COLLECTION_CASES}
WHERE {nonempty_sql("props -> 'related_cases'")}
ORDER BY key
"""


def related_cases(store: Store) -> Iterator[dict[str, Any]]:
    """``{id, kind, dossier_numbers, related_cases}`` of every case the Kamer relates to
    another."""
    return store.query(_RELATED_CASES_SQL)
