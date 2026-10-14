"""The reads of the semantic phase for the Tweede and Eerste Kamer: the papers a step scans,
the memoranda and their targets, and the signals of how a dossier ended.

A read whose order ArangoDB left open comes in the order of the keys, so a run reads the same
rows in the same order every time; a list within a row in the order of its edges' keys.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from lawgraph.config.constants import (
    CHAMBER_EK,
    CHAMBER_TK,
    COLLECTION_ACTIVITIES,
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
    RELATION_ESTABLISHES,
    RELATION_EXPLAINS,
    RELATION_INTRODUCES,
    RELATION_LEGISLATED_IN,
    RELATION_MADE_IN,
    RELATION_PART_OF,
    RELATION_REPEALS,
    RELATION_REVISES,
    RELATION_SAME_AS,
    RELATION_SECOND_READING_OF,
    SOURCE_EERSTEKAMER,
)
from lawgraph.core.models import make_node_key
from lawgraph.core.tk_records import KIND_AMENDMENT, KIND_BILL, KIND_MOTION
from lawgraph.db._rows import node_doc
from lawgraph.db.counting import Store
from lawgraph.db.queries.semantic import (
    absent_sql,
    nonempty_sql,
    present_sql,
    slim_sql,
)
from lawgraph.db.schema import feed_title

# What a dossier did to an article: changed it, or set it by enacting a new law.
_CHANGE_RELATIONS = (
    RELATION_AMENDS,
    RELATION_INTRODUCES,
    RELATION_REPEALS,
    RELATION_ESTABLISHES,
)

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


def tk_documents(
    store: Store,
    ids: list[str] | None,
    *,
    after: str | None = None,
    limit: int | None = None,
) -> Iterator[dict[str, Any]]:
    """The Tweede Kamer documents with the props ``semantic tk`` reads (title, text,
    footnotes and the sections that place a citation; not the record they came with), only those with an external id in *ids* when
    it is given. A slice: past the document key *after*, *limit* of them."""
    clauses = [f"'{CHAMBER_TK}' = ANY(d.labels)"]
    if ids is not None:
        clauses.append("lg_str(d.props -> 'external_id') = ANY(%(ids)s::text[])")
    if after:
        clauses.append("d.key > %(after)s")
    sql = f"""
        SELECT d.id, d.key, d.type, d.labels,
               coalesce({_cut("d", "title", "text", "footnotes", "sections")}, '{{}}'::json) AS props
        FROM {COLLECTION_DOCUMENTS} d
        WHERE {" AND ".join(clauses)}
        ORDER BY d.key
        {"LIMIT %(limit)s" if limit is not None else ""}
        """
    return (
        node_doc(row)
        for row in store.query(sql, {"ids": ids, "after": after, "limit": limit})
    )


def tk_document_titles(
    store: Store, since_date: str | None
) -> Iterator[dict[str, Any]]:
    """The Tweede Kamer documents with their kind, their title, their dossiers and, of a paper
    named by its own subject, the title of its dossier; those of *since_date* or later when it
    is given."""
    # ``doc.props.date >= @since``: a string by the collation; an array or an object sorts
    # above every string in ArangoDB, so it passes too
    since_filter = ""
    if since_date is not None:
        since_filter = (
            "AND (d.date >= %(since)s OR (d.date IS NULL"
            " AND json_typeof(d.props -> 'date') IN ('array', 'object')))"
        )
    sql = f"""
        SELECT {
        slim_sql(
            "d", "kind", "title", "dossier_title", "display_name", "dossier_numbers"
        )
    }
        FROM {COLLECTION_DOCUMENTS} d
        WHERE '{CHAMBER_TK}' = ANY(d.labels) {since_filter}
        ORDER BY d.key
        """
    return store.query(sql, {"since": since_date})


# The papers whose subject (else title) says "kamerstuk": through the trigram index of the
# title the feed shows (``documents_feed_title_g``), which is that text folded.
_NAMING_KAMERSTUKKEN_SQL = f"""
SELECT d.id, d.kind,
       (CASE WHEN lg_truthy(d.pj_subject) THEN d.pj_subject ELSE d.pj_title END) #>> '{{}}'
           AS subject
FROM {COLLECTION_DOCUMENTS} d
WHERE {feed_title("d")} LIKE '%%kamerstuk%%'
"""


def papers_naming_kamerstukken(
    store: Store, ids: list[str] | None
) -> Iterator[dict[str, Any]]:
    """``{id, kind, subject}`` of every paper whose subject, or else its title, names a
    Kamerstuk; only those of *ids* (node ids) when it is given."""
    only = "AND d.id = ANY(%(ids)s::text[])" if ids is not None else ""
    return store.query(
        f"{_NAMING_KAMERSTUKKEN_SQL} {only} ORDER BY d.key", {"ids": ids}
    )


def letters_naming_motions(
    store: Store, kind: str, ids: list[str] | None
) -> Iterator[dict[str, Any]]:
    """``{id, text, footnotes}`` of every paper of *kind* (a letter of the government)
    whose text names a motion ("motie"), by key; only those of *ids* (node ids) when it is
    given. The kind is a column, the text is read only of those."""
    only = "AND d.id = ANY(%(ids)s::text[])" if ids is not None else ""
    return store.query(
        f"""
        SELECT d.id, d.props ->> 'text' AS text, d.props -> 'footnotes' AS footnotes
        FROM {COLLECTION_DOCUMENTS} d
        WHERE d.kind = %(kind)s AND d.props ->> 'text' ILIKE '%%motie%%' {only}
        ORDER BY d.key
        """,
        {"kind": kind, "ids": ids},
    )


def dossier_labels(store: Store) -> set[str]:
    """The label of every dossier (``36945-XIV``, ``21501-02``, ``36799``)."""
    return {
        str(label)
        for label in store.query(
            f"SELECT label FROM {COLLECTION_DOSSIERS} WHERE label IS NOT NULL"
        )
    }


def papers_by_number(
    store: Store, papers: list[tuple[str, str, int]]
) -> Iterator[dict[str, Any]]:
    """``{number, suffix, sequence, id, kind}`` of the paper of each ``(dossier number,
    suffix or "", sequence)`` in *papers* that is in the graph: one probe of the index of
    ``lg_document_light`` each (``queries/lookup.find_document``)."""
    return store.query(
        """
        SELECT k.number, k.suffix, k.sequence, l.id, lg_str(l.props -> 'kind') AS kind
        FROM unnest(%(numbers)s::text[], %(suffixes)s::text[], %(sequences)s::int[])
            AS k(number, suffix, sequence)
        CROSS JOIN LATERAL (
            SELECT l.id, l.props FROM lg_document_light l
            WHERE lg_str(l.props -> 'dossier_number') = k.number
              AND upper(coalesce(lg_str(l.props -> 'dossier_suffix'), '')) = k.suffix
              AND lg_num(l.props -> 'sequence') = k.sequence
            ORDER BY l.id
            LIMIT 1
        ) l
        """,
        {
            "numbers": [number for number, _, _ in papers],
            "suffixes": [suffix.upper() for _, suffix, _ in papers],
            "sequences": [sequence for _, _, sequence in papers],
        },
    )


def acts_of_dossiers(store: Store) -> dict[str, set[str]]:
    """Dossier label -> the ids of the instruments ``LEGISLATED_IN`` it: the acts a dossier
    made (the BWB names its dossier in the brondata of the act)."""
    rows = store.query(
        f"""
        SELECT ds.label, l.from_id
        FROM {COLLECTION_EDGES} l
        JOIN {COLLECTION_DOSSIERS} ds ON ds.id = l.to_id
        WHERE l.relation = %(legislated_in)s AND ds.label IS NOT NULL
        ORDER BY ds.label ASC NULLS FIRST, l.from_id ASC NULLS FIRST
        """,
        {"legislated_in": RELATION_LEGISLATED_IN},
    )
    acts: dict[str, set[str]] = {}
    for row in rows:
        acts.setdefault(row["label"], set()).add(row["from_id"])
    return acts


def own_acts(acts: Mapping[str, set[str]], props: Mapping[str, Any]) -> set[str]:
    """The ids of the acts the dossiers of a paper (*props*) made, of *acts*
    (``acts_of_dossiers``)."""
    return {
        act
        for label in props.get("dossier_numbers") or ()
        for act in acts.get(str(label), ())
    }


_TO_SCAN_FOR_AMENDMENTS_SQL = f"""
SELECT {slim_sql("c", "bwb_id", "text", "sections", "dossier_numbers")}
FROM (
    SELECT d.id, d.key, d.type, d.labels, coalesce(p.props, '{{}}'::json) AS props
    FROM {COLLECTION_DOCUMENTS} d
    CROSS JOIN LATERAL (
        SELECT {_cut("d", "bwb_id", "text", "sections", "dossier_numbers")} AS props OFFSET 0
    ) p
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
    their id in *amending*; with their ``dossier_numbers``."""
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


# The other dossiers an Eerste Kamer paper names (``dossier_numbers`` past its first), by the
# label of the dossier: a paper on more than one bill.
_EK_PAPERS_OTHER_SQL = f"""
SELECT json_build_object(
    'document_key', d.key,
    'dossier_key', ds.key,
    'dossier_number', ds.number,
    'dossier_suffix', ds.props -> 'suffix'
)
FROM {COLLECTION_DOCUMENTS} d
CROSS JOIN LATERAL unnest(d.dossier_numbers[2:]) AS l(label)
JOIN {COLLECTION_DOSSIERS} ds ON ds.label = l.label
WHERE d.source = %(source)s AND cardinality(d.dossier_numbers) > 1
ORDER BY d.key, ds.key
"""


def ek_papers_in_other_dossiers(store: Store) -> Iterator[dict[str, Any]]:
    """``{document_key, dossier_key, dossier_number, dossier_suffix}`` of the other dossiers
    an Eerste Kamer paper names, past the first that ``ek_papers_in_tk_dossiers`` matches,
    that are in the graph."""
    return store.query(_EK_PAPERS_OTHER_SQL, {"source": SOURCE_EERSTEKAMER})


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
# Which papers: a memorandum with article headings, not of a budget.
_MEMORANDA = f"""{_EXPLANATORY}
      AND lg_bool(c.p -> 'budget') IS DISTINCT FROM true
      AND lg_str(c.p -> 'structure_quality') = ANY(%(qualities)s::text[])"""

# ... or an adopted amendment: the last of its chain (no paper REVISES it), and the latest
# decision with an outcome on a case it is part of passed.
_ADOPTED_AMENDMENTS = f"""starts_with(d.kind, '{KIND_AMENDMENT}')
      AND NOT EXISTS (
          SELECT 1 FROM {COLLECTION_EDGES} r
          WHERE r.to_id = d.id AND r.relation = %(revises)s
            AND r.from_collection = '{COLLECTION_DOCUMENTS}'
      )
      AND (
          SELECT dc.passed
          FROM {COLLECTION_EDGES} pc
          JOIN {COLLECTION_EDGES} ab
            ON ab.to_id = pc.to_id AND ab.relation = %(about)s
           AND ab.from_collection = '{COLLECTION_DECISIONS}'
          JOIN {COLLECTION_DECISIONS} dc ON dc.id = ab.from_id
          WHERE pc.from_id = d.id AND pc.relation = %(part_of)s
            AND pc.to_collection = '{COLLECTION_CASES}' AND dc.passed IS NOT NULL
          ORDER BY dc.date DESC NULLS LAST, dc.key DESC
          LIMIT 1
      ) IS TRUE"""


def _papers_with_sections_sql(papers: str) -> str:
    """The rows of ``memoranda_with_sections`` for the papers *papers* selects."""
    return f"""
SELECT json_build_object(
    'document', d.id,
    'text', d.p -> 'text',
    'sections', d.p -> 'sections',
    'own', own.own,
    'changes', ch.changes,
    'laws', laws.laws,
    'bill', bill.text
)
FROM (
    SELECT d.id, d.key, c.p
    FROM {COLLECTION_DOCUMENTS} d
    CROSS JOIN LATERAL (
        SELECT {_cut("d", "budget", "structure_quality", "text", "sections")} AS p
        OFFSET 0
    ) c
    WHERE {papers}
      AND {present_sql("c.p -> 'text'")}
) d
{_LEGISLATED}
-- the bill the memorandum explains: the first Voorstel van wet of its own dossier (its
-- letters are those of the headings "Artikel I, onderdeel B"); the text of that one only
LEFT JOIN LATERAL (
    SELECT b.props -> 'text' AS text
    FROM unnest(o.own_dossiers) AS u(dossier)
    JOIN {COLLECTION_EDGES} e
      ON e.to_id = u.dossier AND e.relation = %(part_of)s
     AND e.from_collection = '{COLLECTION_DOCUMENTS}'
    JOIN {COLLECTION_DOCUMENTS} b ON b.id = e.from_id
    WHERE starts_with(b.kind, '{KIND_BILL}')
    ORDER BY b.date NULLS LAST, b.key
    LIMIT 1
) bill ON true
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
    laws involved, and the text of the bill of its dossier (``bill``, null without one).
    The dossier of a first reading of a change in the Grondwet counts with the dossier of
    its second reading, in which the change was made law."""
    params: dict[str, Any] = {
        "qualities": qualities,
        "part_of": RELATION_PART_OF,
        "legislated_in": RELATION_LEGISLATED_IN,
        "second_reading_of": RELATION_SECOND_READING_OF,
        "change_relations": list(_CHANGE_RELATIONS),
    }
    return store.query(
        _papers_with_sections_sql(_MEMORANDA), params, batch_size=batch_size
    )


def adopted_amendments_with_sections(
    store: Store, *, batch_size: int
) -> Iterator[dict[str, Any]]:
    """``memoranda_with_sections`` for the adopted amendments: the last of a chain whose
    case was decided and passed, each with the dossier's changes, laws and bill."""
    params: dict[str, Any] = {
        "part_of": RELATION_PART_OF,
        "legislated_in": RELATION_LEGISLATED_IN,
        "second_reading_of": RELATION_SECOND_READING_OF,
        "change_relations": list(_CHANGE_RELATIONS),
        "revises": RELATION_REVISES,
        "about": RELATION_ABOUT,
    }
    return store.query(
        _papers_with_sections_sql(_ADOPTED_AMENDMENTS), params, batch_size=batch_size
    )


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
          -- the votes on the bill, not those on a motion about it
          AND lg_str(dc.props -> 'kind') IS DISTINCT FROM '{KIND_MOTION}'
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


def case_papers(store: Store, cases: list[str]) -> dict[str, dict[str, Any]]:
    """Per case of *cases* (TK ids) that is stored: its ``number`` and its ``papers`` of its
    own kind (a letter of a ``Brief regering``, the motion of a ``Motie``, not an
    attachment), each ``{id, kind, dossier_number, dossier_suffix, sequence, date}``, by
    date and id."""
    found: dict[str, dict[str, Any]] = {}
    for row in store.query(
        f"""
        SELECT lg_str(c.props -> 'external_id') AS case_id,
               lg_str(c.props -> 'number') AS number,
               (
                   SELECT coalesce(json_agg(json_build_object(
                       'id', l.id, 'kind', l.props -> 'kind',
                       'dossier_number', l.props -> 'dossier_number',
                       'dossier_suffix', l.props -> 'dossier_suffix',
                       'sequence', l.props -> 'sequence', 'date', l.props -> 'date'
                   ) ORDER BY lg_str(l.props -> 'date') ASC NULLS LAST, l.id), '[]'::json)
                   FROM {COLLECTION_EDGES} e
                   JOIN lg_document_light l ON l.id = e.from_id
                   WHERE e.to_id = c.id AND e.relation = '{RELATION_PART_OF}'
                     AND e.from_collection = '{COLLECTION_DOCUMENTS}'
                     AND starts_with(coalesce(lg_str(l.props -> 'kind'), ''),
                                     coalesce(lg_str(c.props -> 'kind'), ''))
               ) AS papers
        FROM {COLLECTION_CASES} c
        WHERE c.key = ANY(%(keys)s::text[])
        ORDER BY c.key
        """,
        {"keys": sorted({make_node_key(case) for case in cases})},
    ):
        found[str(row["case_id"])] = {"number": row["number"], "papers": row["papers"]}
    return found


# A motion submitted in a debate: the debate has the motion's case on its agenda
# (``Agendapunt.Zaak``), was held (``Uitgevoerd``) on the day the case started
# (``Zaak.GestartOp``, the day it was submitted), and took no decision on it: the vote on a
# motion is an activity of its own (``Stemmingen``) that has the case on its agenda too.
_MOTIONS_SUBMITTED_SQL = f"""
SELECT DISTINCT p.from_id AS paper, a.id AS activity
FROM {COLLECTION_ACTIVITIES} a
JOIN {COLLECTION_EDGES} ab ON ab.from_id = a.id AND ab.relation = '{RELATION_ABOUT}'
    AND ab.to_collection = '{COLLECTION_CASES}'
JOIN {COLLECTION_CASES} c ON c.id = ab.to_id
JOIN {COLLECTION_EDGES} p ON p.to_id = c.id AND p.relation = '{RELATION_PART_OF}'
    AND p.from_collection = '{COLLECTION_DOCUMENTS}'
JOIN lg_document_light l ON l.id = p.from_id
WHERE starts_with(coalesce(lg_str(c.props -> 'kind'), ''), %(motion)s)
  AND starts_with(coalesce(lg_str(l.props -> 'kind'), ''), %(motion)s)
  AND lg_str(a.props -> 'status') = %(held)s
  AND a.date = lg_str(c.props -> 'started_on')
  AND NOT EXISTS (
      SELECT 1
      FROM {COLLECTION_EDGES} m
      JOIN {COLLECTION_EDGES} d ON d.from_id = m.from_id
          AND d.relation = '{RELATION_ABOUT}' AND d.to_id = c.id
      WHERE m.to_id = a.id AND m.relation = '{RELATION_MADE_IN}'
        AND m.from_collection = '{COLLECTION_DECISIONS}'
  )
ORDER BY paper NULLS LAST, activity NULLS LAST
"""


def motions_submitted(store: Store, motion: str, held: str) -> Iterator[dict[str, Any]]:
    """``{paper, activity}``: each motion (a paper of a kind starting with *motion*) and the
    debate it was submitted in (``_MOTIONS_SUBMITTED_SQL``; *held* is the status of an
    activity that took place)."""
    return store.query(_MOTIONS_SUBMITTED_SQL, {"motion": motion, "held": held})


def replacing_cases(store: Store) -> Iterator[dict[str, Any]]:
    """``{id, replaces}`` of every case that replaces another (``Zaak.VervangenVanuit``):
    its node id and the TK ids of the cases it replaces."""
    return store.query(
        f"""
        SELECT id, props -> 'replaces_cases' AS replaces
        FROM {COLLECTION_CASES}
        WHERE {nonempty_sql("props -> 'replaces_cases'")}
        ORDER BY key
        """
    )


def papers_of_cases(store: Store, cases: list[str]) -> dict[str, list[str]]:
    """Per case of *cases* (node ids) the papers that are ``PART_OF`` it, in id order."""
    found: dict[str, list[str]] = {}
    for row in store.query(
        f"""
        SELECT e.to_id AS case_id, e.from_id AS paper
        FROM {COLLECTION_EDGES} e
        WHERE e.to_id = ANY(%(cases)s::text[]) AND e.relation = '{RELATION_PART_OF}'
          AND e.from_collection = '{COLLECTION_DOCUMENTS}'
        ORDER BY e.to_id, e.from_id
        """,
        {"cases": cases},
    ):
        found.setdefault(row["case_id"], []).append(row["paper"])
    return found


# The edges written since *since* that a step reads: of the relations *written*, and not
# to a collection that *skipped* names for its relation (``AUTHORED>cases``).
_WRITTEN = """
    e.created_at >= %(since)s AND e.relation = ANY(%(written)s::text[])
    AND NOT (e.relation || '>' || e.to_collection) = ANY(%(skipped)s::text[])
"""

# What a poll touched: the nodes *ids* (made of the raw records it fetched), the dossiers of
# the Kamerstukdossier records *guids* (a dossier's key is its number), and both ends of
# every edge written since *since* that the step reads (``_WRITTEN``); and the dossiers
# they belong to: a touched dossier, the dossier a touched paper, case, decision or
# instrument is PART_OF, ABOUT or LEGISLATED_IN, directly or through its case.
# ``created_at`` is set when an edge is inserted, never after.
_TOUCHED_DOSSIERS_SQL = f"""
WITH seeds AS (
    SELECT unnest(%(ids)s::text[]) AS id
    UNION
    SELECT d.id FROM {COLLECTION_DOSSIERS} d
    WHERE lg_str(d.props -> 'external_id') = ANY(%(guids)s::text[])
    UNION
    SELECT e.from_id FROM {COLLECTION_EDGES} e WHERE {_WRITTEN}
    UNION
    SELECT e.to_id FROM {COLLECTION_EDGES} e WHERE {_WRITTEN}
),
parts AS (
    SELECT id FROM seeds
    UNION
    SELECT e.to_id FROM {COLLECTION_EDGES} e JOIN seeds s ON e.from_id = s.id
    WHERE e.relation = %(part_of)s AND e.to_collection = '{COLLECTION_CASES}'
),
touched AS (
    SELECT id FROM parts
    UNION
    SELECT e.to_id FROM {COLLECTION_EDGES} e JOIN parts p ON e.from_id = p.id
    WHERE e.relation = ANY(%(relations)s::text[])
      AND e.to_collection = '{COLLECTION_DOSSIERS}'
)
SELECT ds.id FROM touched t JOIN {COLLECTION_DOSSIERS} ds ON ds.id = t.id
ORDER BY ds.key
"""


def touched_dossier_ids(
    store: Store,
    ids: list[str],
    guids: list[str],
    since_iso: str,
    written: dict[str, tuple[str, ...]],
) -> list[str]:
    """The ``_id`` of the dossiers the nodes *ids*, the dossier records *guids*, or an
    edge written at or after *since_iso* belong to (see ``_TOUCHED_DOSSIERS_SQL``): an edge
    of a relation in *written*, not to a collection it names for that relation."""
    params = {
        "ids": ids,
        "guids": guids,
        "since": since_iso,
        **_written_params(written),
        "part_of": RELATION_PART_OF,
        "relations": [RELATION_PART_OF, RELATION_ABOUT, RELATION_LEGISLATED_IN],
    }
    return list(store.query(_TOUCHED_DOSSIERS_SQL, params))


def touched_ids(
    store: Store,
    collection: str,
    ids: list[str],
    since_iso: str,
    written: dict[str, tuple[str, ...]],
) -> list[str]:
    """The ``_id`` of the nodes of *collection* among *ids* or at an end of an edge
    written at or after *since_iso* (of *written*, as ``touched_dossier_ids``)."""
    return list(
        store.query(
            f"""
            SELECT n.id FROM {collection} n
            WHERE n.id = ANY(%(ids)s::text[])
               OR n.id IN (SELECT e.from_id FROM {COLLECTION_EDGES} e WHERE {_WRITTEN})
               OR n.id IN (SELECT e.to_id FROM {COLLECTION_EDGES} e WHERE {_WRITTEN})
            ORDER BY n.key
            """,
            {"ids": ids, "since": since_iso, **_written_params(written)},
        )
    )


def _written_params(written: dict[str, tuple[str, ...]]) -> dict[str, list[str]]:
    return {
        "written": sorted(written),
        "skipped": sorted(
            f"{r}>{c}" for r, targets in written.items() for c in targets
        ),
    }


def activity_numbers(store: Store) -> Iterator[dict[str, Any]]:
    """``{id, number, replaced_by}`` of every activity with a number: what an activity that
    was moved names (``Activiteit.VervangenDoor``) is the number of the one that replaced it."""
    sql = f"""
        SELECT a.id, lg_str(a.props -> 'number') AS number,
               a.props -> 'replaced_by' AS replaced_by
        FROM {COLLECTION_ACTIVITIES} a
        WHERE coalesce(lg_str(a.props -> 'number'), '') <> ''
        ORDER BY a.key
        """
    return store.query(sql)


# The initials of a member as letters alone, upper-case: ``P.J.H.M.`` and ``PJHM`` alike.
_INITIALS = "upper(regexp_replace(coalesce({m}.props ->> 'initials', ''), '[^[:alpha:]]', '', 'g'))"


def person_duplicate_candidates(store: Store, source: str) -> list[str]:
    """The ids of the members a run of *source* reads: those without a role (``member_role``),
    who could be a duplicate, and those it made a ``SAME_AS`` from before (one that has a role
    now loses it)."""
    from lawgraph.db.queries import member_role

    return list(
        store.query(
            f"""
            SELECT m.id FROM members m WHERE NOT {member_role.has_role("m")}
            UNION
            SELECT e.from_id FROM edges e
            WHERE e.relation = %(relation)s AND e.source = %(source)s
              AND e.from_collection = 'members'
            ORDER BY 1
            """,
            {"relation": RELATION_SAME_AS, "source": source},
        )
    )


def person_duplicates(store: Store) -> list[dict[str, Any]]:
    """``{from_id, to_id}``: a member without a role and the one member with a role of the same
    birth date, surname and initials (all three given and equal; the initials as letters
    alone), the same person under a second ``Persoon`` of the Tweede Kamer. A member without a
    role that matches two members with one is in none."""
    from lawgraph.db.queries import member_role

    bare, kept = _INITIALS.format(m="b"), _INITIALS.format(m="k")
    return list(
        store.query(
            f"""
            SELECT b.id AS from_id, min(k.id) AS to_id
            FROM members b
            JOIN members k
              ON k.props ->> 'birth_date' = b.props ->> 'birth_date'
             AND k.props ->> 'family_name' = b.props ->> 'family_name'
             AND {kept} = {bare}
             AND k.id <> b.id
            WHERE NOT {member_role.has_role("b")} AND {member_role.has_role("k")}
              AND b.props ->> 'birth_date' IS NOT NULL
              AND b.props ->> 'family_name' IS NOT NULL
              AND {bare} <> ''
            GROUP BY b.id
            HAVING count(*) = 1
            ORDER BY b.id
            """
        )
    )


# The edges of *source* from a paper to an act its own dossier made (the act LEGISLATED_IN
# a dossier the paper is in), or to an article of one: a bill and its papers make that act,
# they do not change it. From the acts, few, through their dossiers to the papers.
_OWN_ACT_EDGES_SQL = f"""
DELETE FROM {COLLECTION_EDGES} e
USING {COLLECTION_EDGES} l, {COLLECTION_DOSSIERS} ds, {COLLECTION_INSTRUMENTS} act,
      {COLLECTION_DOCUMENTS} d
WHERE l.relation = %(legislated_in)s AND l.to_collection = '{COLLECTION_DOSSIERS}'
  AND ds.id = l.to_id AND ds.label IS NOT NULL
  AND act.id = l.from_id
  AND d.dossier_numbers @> ARRAY[ds.label]
  AND e.from_id = d.id
  AND e.relation = ANY(%(relations)s) AND e.source = %(source)s
  AND (e.to_id = act.id OR EXISTS (
      SELECT 1 FROM {COLLECTION_ARTICLES} a
      WHERE a.id = e.to_id AND a.bwb_id = lg_str(act.props -> 'bwb_id')
  ))
RETURNING e.from_id, e.to_id
"""


def remove_own_act_edges(store: Store, relations: list[str], source: str) -> int:
    """Remove the edges of *relations* made by *source* from a paper to the act its own
    dossier made, or to an article of that act (``_OWN_ACT_EDGES_SQL``). How many went."""
    return len(
        store.execute(
            _OWN_ACT_EDGES_SQL,
            {
                "legislated_in": RELATION_LEGISLATED_IN,
                "relations": relations,
                "source": source,
            },
        )
    )
