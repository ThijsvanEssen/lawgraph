"""The graph reads of the normalize phase for the Tweede and Eerste Kamer and the
government: stored cases, dossiers and members, the signals of a dossier, the
government signatures and the composition of the Eerste Kamer.

A read whose order ArangoDB left open comes in the byte order of the keys."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from psycopg import sql

from lawgraph.config.constants import (
    CHAMBER_TK,
    COLLECTION_ACTIVITIES,
    COLLECTION_CASES,
    COLLECTION_COMMITTEES,
    COLLECTION_DECISIONS,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_EDGES,
    COLLECTION_FACTIONS,
    COLLECTION_MEMBERS,
    RELATION_ABOUT,
    RELATION_AUTHORED,
    RELATION_MEMBER_OF,
    RELATION_PART_OF,
    RELATION_VOTED,
)
from lawgraph.core.dossier_stages import LEGISLATIVE_KINDS
from lawgraph.core.tk_records import CAPACITY_GOVERNMENT
from lawgraph.db.counting import Store
from lawgraph.db.queries.normalize import edges as normalize_edges
from lawgraph.db.queries.semantic import absent_sql, present_sql

# ``dossier_numbers`` read once per case (a case holds its API payload).
_CASE_NUMBERS_SQL = f"""
SELECT c.id, x.numbers AS dossier_numbers
FROM {COLLECTION_CASES} c
CROSS JOIN LATERAL (SELECT c.props -> 'dossier_numbers' AS numbers OFFSET 0) x
WHERE {present_sql("x.numbers")}
ORDER BY c.key COLLATE "C"
"""


def case_dossier_numbers(store: Store) -> Iterator[dict[str, Any]]:
    """``{id, dossier_numbers}`` of every case that names a dossier."""
    return store.query(_CASE_NUMBERS_SQL)


# One pass over the props of each node: its ``external_id`` and the props kept, in the
# byte order of their names as ``KEEP`` gave them.
_BY_EXTERNAL_ID_SQL = """
SELECT n.key, x.external_id AS id, x.props
FROM {} n
CROSS JOIN LATERAL (
    SELECT (array_agg(j.value) FILTER (WHERE j.key = 'external_id'))[1] AS external_id,
           coalesce(json_object_agg(j.key, j.value ORDER BY j.key COLLATE "C")
                        FILTER (WHERE j.key = ANY(%(names)s::text[])), '{{}}') AS props
    FROM json_each(n.props) AS j(key, value)
) x
WHERE {}
ORDER BY n.key COLLATE "C"
"""


def nodes_by_external_id(
    store: Store, collection: str, names: list[str]
) -> Iterator[dict[str, Any]]:
    """``{key, id, props}`` of the nodes of *collection* with a TK ``Id``; the props only
    *names*."""
    statement = sql.SQL(_BY_EXTERNAL_ID_SQL).format(
        sql.Identifier(collection), sql.SQL(present_sql("x.external_id"))
    )
    return store.query(statement, {"names": names})


def faction_aliases(store: Store) -> Iterator[Any]:
    """Every alias a stored faction carries."""
    aliases = "f.props -> 'aliases'"
    statement = f"""
    SELECT a.v::json
    FROM (
        SELECT DISTINCT x.v::jsonb AS v
        FROM {COLLECTION_FACTIONS} f
        CROSS JOIN LATERAL json_array_elements(
            CASE WHEN lg_truthy({aliases}) THEN {aliases} ELSE '[]'::json END
        ) AS x(v)
    ) a
    ORDER BY {_json_keys("a.v::json")}
    """
    return store.query(statement)


def dossier_case_kinds(store: Store, keys: list[str]) -> Iterator[dict[str, Any]]:
    """``{key, case_kinds}`` of the dossiers with these *keys*."""
    lookup = f"""
    SELECT key, props -> 'case_kinds' AS case_kinds
    FROM {COLLECTION_DOSSIERS}
    WHERE key = ANY(%(keys)s::text[])
    ORDER BY key COLLATE "C"
    """
    return store.query(lookup, {"keys": keys})


def _cut(alias: str, fields: str) -> str:
    """The props of *alias* cut down to *fields* (a bind of names) in one pass: a TK
    document holds its whole payload, and every ``->`` on it parses it again."""
    return f"""(
        SELECT json_object_agg(j.key, j.value)
        FROM json_each({alias}.props) AS j(key, value)
        WHERE j.key = ANY(%({fields})s::text[])
    )"""


def _spliced(value: str) -> str:
    """The values of *value* as ``FLATTEN`` splices it: its elements when it is an array,
    else itself."""
    return (
        f"json_array_elements(CASE WHEN json_typeof({value}) = 'array'"
        f" THEN {value} ELSE json_build_array({value}) END)"
    )


def _json_keys(value: str) -> str:
    """ORDER BY items that sort a json value as ArangoDB does: by its type (null, boolean,
    number, string, array, object), then a string by the collation, a number, a boolean."""
    rank = (
        f"CASE coalesce(json_typeof({value}), 'null') WHEN 'null' THEN 0"
        " WHEN 'boolean' THEN 1 WHEN 'number' THEN 2 WHEN 'string' THEN 3"
        " WHEN 'array' THEN 4 ELSE 5 END"
    )
    keys = [f"{f}({value}) ASC NULLS FIRST" for f in ("lg_str", "lg_num", "lg_bool")]
    return ", ".join([f"{rank} ASC", *keys])


def _length(value: str) -> str:
    """``LENGTH(value)`` of a json value as ArangoDB counts it."""
    text = f"({value} #>> '{{}}')"
    return f"""CASE json_typeof({value})
        WHEN 'array' THEN json_array_length({value})
        WHEN 'string' THEN char_length{text}
        WHEN 'number' THEN char_length{text}
        WHEN 'object' THEN (SELECT count(*) FROM json_each({value}))::int
        WHEN 'boolean' THEN CASE WHEN {text}::boolean THEN 1 ELSE 0 END
        ELSE 0 END"""


def _present(value: str) -> str:
    """``value != null`` of a json value."""
    return f"coalesce(json_typeof({value}), 'null') <> 'null'"


def _first_present(*values: str) -> str:
    """``NOT_NULL(a, b, ...)`` of json values."""
    cases = " ".join(f"WHEN {_present(v)} THEN {v}" for v in values)
    return f"CASE {cases} END"


_SIGNAL_TITLE = _first_present(
    "c.p -> 'dossier_title'", "c.p -> 'title'", "c.p -> 'display_name'"
)
_SIGNAL_NUMBERS = _length("c.p -> 'dossier_numbers'")
_OWN_NUMBER = _present("c.p -> 'dossier_number'")
_DOC_CUT = _cut("d", "doc_fields")
_SUBJECT_CUT = _cut("t", "subject_fields")
_STORED_KINDS = _spliced("ds.props -> 'case_kinds'")
_STORED_KIND_PARTS = _spliced("e.v")
_CASE_KIND = _spliced("cs.props -> 'kind'")
_DOC_KINDS = _spliced("s.signal -> 'case_kinds'")
_KIND_ORDER = _json_keys("k.v::json")
_DOC_ORDER = _json_keys("s.date")
_SUBJECT_ORDER = _json_keys("n.p -> 'date'")

# ``asked``: the dossiers in their order; ``member_docs``: the documents PART_OF each,
# directly or through one of its cases, once per edge; ``signals``: the few fields of each
# document, from its props cut down once (``cut``); ``subjects``: the activities and
# decisions ABOUT each, from their props cut down once. A doc and a decision come out
# with their keys in byte order, as ``UNSET`` gave them.
_DOSSIER_SIGNALS_SQL = f"""
WITH asked AS (
    SELECT a.dossier_id, a.ord
    FROM unnest(%(dossier_ids)s::text[]) WITH ORDINALITY AS a(dossier_id, ord)
),
own_cases AS (
    SELECT a.ord, e.from_id AS case_id
    FROM asked a
    JOIN {COLLECTION_EDGES} e
      ON e.to_id = a.dossier_id AND e.relation = %(part_of)s
     AND e.from_collection = '{COLLECTION_CASES}'
),
member_docs AS (
    SELECT a.ord, e.from_id AS doc_id
    FROM asked a
    JOIN {COLLECTION_EDGES} e
      ON e.to_id = a.dossier_id AND e.relation = %(part_of)s
     AND e.from_collection = '{COLLECTION_DOCUMENTS}'
    UNION ALL
    SELECT o.ord, e2.from_id
    FROM own_cases o
    JOIN {COLLECTION_EDGES} e2
      ON e2.to_id = o.case_id AND e2.relation = %(part_of)s
     AND e2.from_collection = '{COLLECTION_DOCUMENTS}'
),
cut AS MATERIALIZED (
    SELECT d.id, {_DOC_CUT} AS p
    FROM {COLLECTION_DOCUMENTS} d
    WHERE d.id IN (SELECT doc_id FROM member_docs)
),
signals AS MATERIALIZED (
    SELECT c.id, c.p -> 'date' AS date, json_build_object(
        'id', c.id,
        'kind', c.p -> 'kind',
        'date', c.p -> 'date',
        'title', {_SIGNAL_TITLE},
        'case_kinds', CASE WHEN ({_SIGNAL_NUMBERS}) = 1
            THEN c.p -> 'case_kinds' ELSE '[]'::json END,
        'own', CASE WHEN {_OWN_NUMBER}
            THEN json_build_array(c.p -> 'dossier_number', c.p -> 'dossier_suffix') END,
        'sequence', c.p -> 'sequence'
    ) AS signal
    FROM cut c
),
subjects AS MATERIALIZED (
    SELECT a.ord, t.id, '{COLLECTION_ACTIVITIES}' AS collection, {_SUBJECT_CUT} AS p
    FROM asked a
    JOIN {COLLECTION_EDGES} e
      ON e.to_id = a.dossier_id AND e.relation = %(about)s
     AND e.from_collection = '{COLLECTION_ACTIVITIES}'
    JOIN {COLLECTION_ACTIVITIES} t ON t.id = e.from_id
    UNION ALL
    SELECT a.ord, t.id, '{COLLECTION_DECISIONS}', {_SUBJECT_CUT}
    FROM asked a
    JOIN {COLLECTION_EDGES} e
      ON e.to_id = a.dossier_id AND e.relation = %(about)s
     AND e.from_collection = '{COLLECTION_DECISIONS}'
    JOIN {COLLECTION_DECISIONS} t ON t.id = e.from_id
)
SELECT
    a.dossier_id,
    (SELECT ds.pj_opened_on FROM {COLLECTION_DOSSIERS} ds WHERE ds.id = a.dossier_id)
        AS opened_on,
    (
        SELECT coalesce(json_agg(k.v::json ORDER BY {_KIND_ORDER}), '[]'::json)
        FROM (
            SELECT DISTINCT flat.x::jsonb AS v
            FROM (
                SELECT f AS x
                FROM {COLLECTION_DOSSIERS} ds
                CROSS JOIN LATERAL {_STORED_KINDS} AS e(v)
                CROSS JOIN LATERAL {_STORED_KIND_PARTS} AS f
                WHERE ds.id = a.dossier_id AND lg_truthy(ds.props -> 'case_kinds')
                UNION ALL
                SELECT f
                FROM own_cases o
                LEFT JOIN {COLLECTION_CASES} cs ON cs.id = o.case_id
                CROSS JOIN LATERAL {_CASE_KIND} AS f
                WHERE o.ord = a.ord
                UNION ALL
                SELECT f
                FROM member_docs m
                JOIN signals s ON s.id = m.doc_id
                CROSS JOIN LATERAL {_DOC_KINDS} AS f
                WHERE m.ord = a.ord
            ) flat
            WHERE {_present("flat.x")}
        ) k
    ) AS case_kinds,
    (
        SELECT coalesce(json_agg(
            json_build_object(
                'date', s.signal -> 'date',
                'kind', s.signal -> 'kind',
                'own', s.signal -> 'own',
                'sequence', s.signal -> 'sequence',
                'title', s.signal -> 'title'
            ) ORDER BY {_DOC_ORDER}, s.id ASC
        ), '[]'::json)
        FROM signals s
        WHERE s.id IN (SELECT m.doc_id FROM member_docs m WHERE m.ord = a.ord)
    ) AS docs,
    (
        SELECT coalesce(json_agg(json_build_object(
            'kind', n.p -> 'kind',
            'date', n.p -> 'date',
            'status', n.p -> 'status'
        ) ORDER BY {_SUBJECT_ORDER}, n.id ASC), '[]'::json)
        FROM subjects n
        WHERE n.ord = a.ord AND n.collection = '{COLLECTION_ACTIVITIES}'
    ) AS activities,
    (
        SELECT coalesce(json_agg(json_build_object(
            'case_kind', n.p -> 'primary_case_kind',
            'date', n.p -> 'date',
            'decision_kind', n.p -> 'decision_kind',
            'decision_text', n.p -> 'decision_text',
            'kind', n.p -> 'kind',
            'passed', n.p -> 'passed'
        ) ORDER BY {_SUBJECT_ORDER}, n.id ASC), '[]'::json)
        FROM subjects n
        WHERE n.ord = a.ord AND n.collection = '{COLLECTION_DECISIONS}'
    ) AS decisions,
    (
        SELECT min(lg_str(cs.props -> 'started_on'))
        FROM own_cases o
        JOIN {COLLECTION_CASES} cs ON cs.id = o.case_id
        WHERE o.ord = a.ord AND lg_str(cs.props -> 'kind') = ANY(%(bill_kinds)s)
    ) AS bill_started_on
FROM asked a
ORDER BY a.ord
"""


def dossier_signals(store: Store, dossier_ids: list[str]) -> Iterator[dict[str, Any]]:
    """Documents, activities and decisions per dossier of *dossier_ids*; its case kinds
    (the ``Zaak.Soort`` of its own zaken: those ``PART_OF`` it, those of its papers that
    belong to it alone, and those rolled up from its activities); and the ``opened_on`` it
    holds.

    Only the few fields that are used are read, from props cut down once per node: a TK
    document holds its text and its payload. ``case_kinds`` is a set to its readers;
    sorted, it is the same list every time.
    """
    bind = {
        "part_of": RELATION_PART_OF,
        "about": RELATION_ABOUT,
        "dossier_ids": dossier_ids,
        "bill_kinds": list(LEGISLATIVE_KINDS),
        "doc_fields": [
            "kind",
            "date",
            "dossier_title",
            "title",
            "display_name",
            "dossier_numbers",
            "case_kinds",
            "dossier_number",
            "dossier_suffix",
            "sequence",
        ],
        "subject_fields": [
            "kind",
            "date",
            "status",
            "passed",
            "decision_kind",
            "decision_text",
            "primary_case_kind",
        ],
    }
    return store.query(_DOSSIER_SIGNALS_SQL, bind)


def dossiers_of_numbers(store: Store, numbers: list[str]) -> Iterator[dict[str, Any]]:
    """``{key, number, same_number_count}`` of every dossier with one of these *numbers*."""
    statement = f"""
    SELECT key, number, props -> 'same_number_count' AS same_number_count
    FROM {COLLECTION_DOSSIERS}
    WHERE number = ANY(%(numbers)s::text[])
    ORDER BY key COLLATE "C"
    """
    return store.query(statement, {"numbers": numbers})


_MEMBER_CUT = _cut("m", "fields")
_FACTION_KEY_ORDER = _json_keys("k.v::json")

# ``name``: ``full_name OR name``; ``factions``: ``SORTED_UNIQUE`` of the ``faction_key``
# of every membership (null for one without; none when the memberships are no array),
# sorted as ArangoDB sorts values.
_IDENTITIES_SQL = f"""
SELECT c.key,
       c.p -> 'family_name' AS family_name,
       CASE WHEN lg_truthy(c.p -> 'full_name') THEN c.p -> 'full_name'
            ELSE c.p -> 'name' END AS name,
       c.p -> 'initials' AS initials,
       c.p -> 'birth_date' AS birth_date,
       (
           SELECT coalesce(json_agg(k.v::json ORDER BY {_FACTION_KEY_ORDER}), '[]'::json)
           FROM (
               SELECT DISTINCT coalesce((f.x -> 'faction_key')::jsonb, 'null') AS v
               FROM json_array_elements(
                   CASE WHEN json_typeof(c.memberships) = 'array'
                        THEN c.memberships ELSE '[]'::json END
               ) AS f(x)
           ) k
       ) AS factions
FROM (
    SELECT m.key, m.pj_faction_memberships AS memberships, {_MEMBER_CUT} AS p
    FROM {COLLECTION_MEMBERS} m
    WHERE %(tk)s = ANY(m.labels)
    OFFSET 0
) c
WHERE {present_sql("c.p -> 'family_name'")}
ORDER BY c.key COLLATE "C"
"""


def member_identities(store: Store) -> Iterator[dict[str, Any]]:
    """``{key, family_name, name, initials, birth_date, factions}`` of every Tweede Kamer
    person with a surname (``normalize rijksoverheid`` matches the bewindspersonen to them):
    ``name`` the full name, ``factions`` the keys of the factions they sat in."""
    bind = {
        "tk": CHAMBER_TK,
        "fields": ["family_name", "full_name", "name", "initials", "birth_date"],
    }
    return store.query(_IDENTITIES_SQL, bind)


# ``MIN`` and ``MAX`` of the dates of a group as ArangoDB orders values: a boolean before a
# number before a string before an array before an object. ``x.date`` is the date when it
# is a string, ``x.other`` the date of another type (the props are read for it alone).
_FIRST = """coalesce(
    to_json(bool_and(lg_bool(x.other))), to_json(min(lg_num(x.other))),
    to_json(min(x.date)),
    (array_agg(x.other) FILTER (WHERE json_typeof(x.other) = 'array'))[1],
    (array_agg(x.other) FILTER (WHERE json_typeof(x.other) = 'object'))[1]
)"""
_LAST = """coalesce(
    (array_agg(x.other) FILTER (WHERE json_typeof(x.other) = 'object'))[1],
    (array_agg(x.other) FILTER (WHERE json_typeof(x.other) = 'array'))[1],
    to_json(max(x.date)), to_json(max(lg_num(x.other))),
    to_json(bool_or(lg_bool(x.other)))
)"""

# The government signatures: the AUTHORED edges in that capacity from a Tweede Kamer person
# (``m``, its props cut down to *fields*) to a document with a date. ``function`` null when
# the edge has none. Read with ``hash_joins``: the planner takes the signatures (a condition
# on ``meta``) for a row or two and loops over them.
_SIGNED = f"""
tk_members AS MATERIALIZED (
    SELECT m.id, m.key, {_MEMBER_CUT} AS p
    FROM {COLLECTION_MEMBERS} m
    WHERE %(tk)s = ANY(m.labels)
),
signed AS (
    SELECT m.key, m.p, d.pj_actors AS actors, x.date, x.other,
           coalesce((e.doc -> 'meta' -> 'function')::jsonb, 'null') AS function
    FROM {COLLECTION_EDGES} e
    JOIN tk_members m ON m.id = e.from_id
    JOIN {COLLECTION_DOCUMENTS} d ON d.id = e.to_id
    CROSS JOIN LATERAL (
        SELECT d.date, CASE WHEN d.date IS NULL THEN d.props -> 'date' END AS other
        OFFSET 0
    ) x
    WHERE e.relation = %(authored)s
      AND e.from_collection = '{COLLECTION_MEMBERS}'
      AND lg_str(e.doc -> 'meta' -> 'capacity') = %(government)s
      AND (x.date IS NOT NULL OR {present_sql("x.other")})
)"""

# Per signature, every actor of the document that is the person (``person_id`` equal to
# their ``external_id``, null equal to null) with a name.
_SIGNATURES_SQL = f"""
WITH {_SIGNED}
SELECT x.key, x.name::json AS name, x.function::json AS function,
       {_FIRST} AS first, {_LAST} AS last
FROM (
    SELECT s.key, s.function, s.date, s.other, (a.v -> 'name')::jsonb AS name
    FROM signed s
    CROSS JOIN LATERAL json_array_elements(
        CASE WHEN lg_truthy(s.actors) THEN s.actors ELSE '[]'::json END
    ) AS a(v)
    WHERE {absent_sql("s.p -> 'family_name'")}
      AND coalesce((a.v -> 'person_id')::jsonb, 'null')
          = coalesce((s.p -> 'external_id')::jsonb, 'null')
      AND {present_sql("a.v -> 'name'")}
) x
GROUP BY x.key, x.name, x.function
ORDER BY x.key ASC, {_json_keys("x.name::json")}, {_json_keys("x.function::json")}
"""


def _signature_bind() -> dict[str, Any]:
    return {
        "authored": RELATION_AUTHORED,
        "government": CAPACITY_GOVERNMENT,
        "tk": CHAMBER_TK,
        "fields": ["family_name", "external_id"],
    }


def government_signatures(store: Store) -> Iterator[dict[str, Any]]:
    """The signatures as a minister or state secretary of the Tweede Kamer persons without a
    name of their own (a minister who never sat in parliament): ``{key, name, function,
    first, last}`` per person, signed name and function, with the first and last date."""
    return store.query(_SIGNATURES_SQL, _signature_bind(), hash_joins=True)


# ``month``: the first seven characters of the date, of the text of a date of another type
# (``SUBSTRING`` of a number or a boolean).
_BY_MONTH_SQL = f"""
WITH {_SIGNED}
SELECT x.key, x.function::json AS function, {_FIRST} AS first, {_LAST} AS last
FROM (
    SELECT s.key, s.function, s.date, s.other,
           left(coalesce(s.date, s.other #>> '{{}}'), 7) AS month
    FROM signed s
) x
GROUP BY x.key, x.function, x.month
ORDER BY x.key ASC, {_json_keys("x.function::json")}, x.month ASC NULLS FIRST
"""


def government_signatures_by_month(store: Store) -> Iterator[dict[str, Any]]:
    """The signatures as a minister or state secretary of every Tweede Kamer person:
    ``{key, function, first, last}`` per person, function and month."""
    return store.query(_BY_MONTH_SQL, _signature_bind(), hash_joins=True)


def labelled_members(store: Store, label: str) -> Iterator[str]:
    """The keys of the members with *label* (``Rijksoverheid``: a bewindspersoon only
    Rijksoverheid knows)."""
    statement = f"""
    SELECT key FROM {COLLECTION_MEMBERS}
    WHERE %(label)s = ANY(labels)
    ORDER BY key COLLATE "C"
    """
    return store.query(statement, {"label": label})


def government_members(store: Store) -> Iterator[str]:
    """The keys of the members that have ``government_functions``."""
    statement = f"""
    SELECT key FROM {COLLECTION_MEMBERS}
    WHERE {present_sql("props -> 'government_functions'")}
    ORDER BY key COLLATE "C"
    """
    return store.query(statement)


def decisions_of_vote_records(
    store: Store, record_ids: list[str]
) -> Iterator[dict[str, Any]]:
    """``{key, decision_id}`` of the decisions the Stemming records *record_ids* voted on,
    by the VOTED edges they made: a vote the Kamer deleted names no decision any more."""
    statement = f"""
    SELECT d.key, d.props -> 'decision_id' AS decision_id
    FROM {COLLECTION_DECISIONS} d
    WHERE d.id IN (
        SELECT e.to_id FROM {COLLECTION_EDGES} e
        WHERE e.record_ids && %(ids)s::text[] AND e.relation = %(voted)s
    )
    ORDER BY d.key COLLATE "C"
    """
    return store.query(statement, {"ids": record_ids, "voted": RELATION_VOTED})


def remove_members(store: Store, keys: list[str]) -> int:
    """Remove the members *keys* with every edge at them; how many members went."""
    return normalize_edges.remove_nodes(store, COLLECTION_MEMBERS, keys)


def faction_names(store: Store) -> Iterator[dict[str, Any]]:
    """``{key, name, abbreviation, aliases}`` of every faction (``normalize rijksoverheid``
    finds the faction of a bewindspersoon's party by them)."""
    statement = f"""
    SELECT key, props -> 'name' AS name, props -> 'abbreviation' AS abbreviation,
           props -> 'aliases' AS aliases
    FROM {COLLECTION_FACTIONS}
    WHERE lg_str(props -> 'chamber') IS DISTINCT FROM 'EK'
    ORDER BY key COLLATE "C"
    """
    return store.query(statement)


# The factions and committees of the Eerste Kamer, its members, and the MEMBER_OF edges
# into those factions and committees: per target (the factions, then the committees), by
# edge key.
_EK_COMPOSITION_SQL = f"""
WITH ek_factions AS (
    SELECT key, props FROM {COLLECTION_FACTIONS} WHERE lg_str(props -> 'chamber') = 'EK'
),
ek_committees AS (
    SELECT key, props FROM {COLLECTION_COMMITTEES} WHERE lg_str(props -> 'chamber') = 'EK'
),
targets AS (
    SELECT '{COLLECTION_FACTIONS}/' || key AS id, 0 AS part, key FROM ek_factions
    UNION ALL
    SELECT '{COLLECTION_COMMITTEES}/' || key, 1, key FROM ek_committees
)
SELECT
    coalesce((
        SELECT json_agg(json_build_object('key', key, 'props', props)
                        ORDER BY key COLLATE "C")
        FROM ek_factions
    ), '[]'::json) AS factions,
    coalesce((
        SELECT json_agg(json_build_object('key', key, 'props', props)
                        ORDER BY key COLLATE "C")
        FROM ek_committees
    ), '[]'::json) AS committees,
    coalesce((
        SELECT json_agg(json_build_object('key', m.key, 'ek', m.props -> 'ek')
                        ORDER BY m.key COLLATE "C")
        FROM {COLLECTION_MEMBERS} m
        WHERE m.in_ek
    ), '[]'::json) AS members,
    coalesce((
        SELECT json_agg(
            json_build_object('from', e.from_id, 'to', e.to_id, 'meta', e.doc -> 'meta')
            ORDER BY t.part, t.key COLLATE "C", e.key COLLATE "C"
        )
        FROM targets t
        JOIN {COLLECTION_EDGES} e ON e.to_id = t.id AND e.relation = %(member_of)s
    ), '[]'::json) AS edges
"""


def ek_composition(store: Store) -> dict[str, Any]:
    """What the graph holds of the composition of the Eerste Kamer: its factions and
    committees (``chamber`` ``EK``) with their props, the members with an ``ek`` prop, and
    the ``MEMBER_OF`` edges into those factions and committees."""
    rows = store.query(_EK_COMPOSITION_SQL, {"member_of": RELATION_MEMBER_OF})
    return dict(next(iter(rows)))


def members_born_on(store: Store, dates: list[str]) -> Iterator[dict[str, Any]]:
    """``{key, family_name, birth_date}`` of the members born on one of *dates*."""
    statement = f"""
    SELECT c.key, c.p -> 'family_name' AS family_name, c.p -> 'birth_date' AS birth_date
    FROM (
        SELECT m.key, {_MEMBER_CUT} AS p FROM {COLLECTION_MEMBERS} m OFFSET 0
    ) c
    WHERE lg_str(c.p -> 'birth_date') = ANY(%(dates)s::text[])
    ORDER BY c.key COLLATE "C"
    """
    bind = {"dates": dates, "fields": ["family_name", "birth_date"]}
    return store.query(statement, bind)


def member_slug_rows(store: Store) -> Iterator[dict[str, Any]]:
    """What a member's slug is made of, of every member (``core.member_slugs.new_slugs``):
    ``key``, ``slug``, ``name``, ``known_as``, ``government_name``, ``birth_date``,
    ``number``."""
    return store.query(
        f"""
        SELECT m.key, lg_str(c.p -> 'slug') AS slug, lg_str(c.p -> 'name') AS name,
               lg_str(c.p -> 'known_as') AS known_as,
               lg_str(c.p -> 'government_name') AS government_name,
               lg_str(c.p -> 'birth_date') AS birth_date,
               lg_str(c.p -> 'number') AS number
        FROM {COLLECTION_MEMBERS} m
        CROSS JOIN LATERAL (
            SELECT json_object_agg(f.key, f.value) AS p
            FROM json_each(m.props) f
            WHERE f.key = ANY(%(fields)s)
            OFFSET 0
        ) c
        ORDER BY m.key COLLATE "C" ASC NULLS FIRST
        """,
        {
            "fields": [
                "slug",
                "name",
                "known_as",
                "government_name",
                "birth_date",
                "number",
            ]
        },
    )
