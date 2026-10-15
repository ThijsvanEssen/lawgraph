"""The graph reads of the normalize phase for the Tweede and Eerste Kamer and the
government: stored cases, dossiers and members, the signals of a dossier, the
government signatures and the composition of the Eerste Kamer.

Rows come in the byte order of the keys, so a run reads them in the same order every time."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from psycopg import sql

from lawgraph.config.constants import (
    CHAMBER_EK,
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
from lawgraph.core.tk_records.actors import CAPACITY_GOVERNMENT
from lawgraph.db.counting import Store
from lawgraph.db.queries import removals
from lawgraph.db.queries._json_sql import (
    array_or_empty,
    first_present,
    is_absent,
    is_present,
    truthy_or,
)

# ``dossier_numbers`` read once per case (a case holds its API payload).
_CASE_NUMBERS_SQL = f"""
SELECT c.id, x.numbers AS dossier_numbers
FROM {COLLECTION_CASES} c
CROSS JOIN LATERAL (SELECT c.props -> 'dossier_numbers' AS numbers OFFSET 0) x
WHERE {is_present("x.numbers")}
ORDER BY c.key COLLATE "C"
"""


def dossiers_by_key(store: Store, keys: list[str]) -> Iterator[dict[str, Any]]:
    """The stored dossiers of *keys*, as rows of ``node_doc``, in one read."""
    return store.query(
        f"""
        SELECT id, key, type, labels, props FROM {COLLECTION_DOSSIERS}
        WHERE key = ANY(%(keys)s::text[])
        ORDER BY key COLLATE "C"
        """,
        {"keys": keys},
    )


def case_dossier_numbers(store: Store) -> Iterator[dict[str, Any]]:
    """``{id, dossier_numbers}`` of every case that names a dossier."""
    return store.query(_CASE_NUMBERS_SQL)


def case_dossier_numbers_of(store: Store, ids: list[str]) -> Iterator[dict[str, Any]]:
    """``{id, dossier_numbers}`` of the cases *ids* (``_id``) that name a dossier."""
    return store.query(
        f"""
        SELECT c.id, x.numbers AS dossier_numbers
        FROM {COLLECTION_CASES} c
        CROSS JOIN LATERAL (SELECT c.props -> 'dossier_numbers' AS numbers OFFSET 0) x
        WHERE c.id = ANY(%(ids)s::text[]) AND {is_present("x.numbers")}
        ORDER BY c.key COLLATE "C"
        """,
        {"ids": ids},
    )


def case_dossier_numbers_naming(
    store: Store, labels: list[str]
) -> Iterator[dict[str, Any]]:
    """``{id, dossier_numbers}`` of the cases that name one of the dossiers *labels*: a
    read of every case (no column holds their dossiers), for a run that wrote dossiers."""
    return store.query(
        f"""
        SELECT c.id, x.numbers AS dossier_numbers
        FROM {COLLECTION_CASES} c
        CROSS JOIN LATERAL (SELECT c.props -> 'dossier_numbers' AS numbers OFFSET 0) x
        WHERE EXISTS (
            SELECT 1 FROM json_array_elements_text({array_or_empty("x.numbers")}) AS n(label)
            WHERE n.label = ANY(%(labels)s::text[])
        )
        ORDER BY c.key COLLATE "C"
        """,
        {"labels": labels},
    )


# One pass over the props of each node: its ``external_id`` and the props kept.
_BY_EXTERNAL_ID_SQL = """
SELECT n.key, x.external_id AS id, x.props
FROM {} n
CROSS JOIN LATERAL (
    SELECT (array_agg(j.value) FILTER (WHERE j.key = 'external_id'))[1] AS external_id,
           coalesce(json_object_agg(j.key, j.value)
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
        sql.Identifier(collection), sql.SQL(is_present("x.external_id"))
    )
    return store.query(statement, {"names": names})


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


def _kinds(value: str) -> str:
    """The case kinds in the json array *value*, as text (none when it is no array)."""
    return f"json_array_elements_text({array_or_empty(value)})"


_SIGNAL_TITLE = first_present(
    "c.p -> 'dossier_title'", "c.p -> 'title'", "c.p -> 'display_name'"
)
_SIGNAL_NUMBERS = (
    "json_array_length(" + array_or_empty("c.p -> 'dossier_numbers'") + ")"
)
_OWN_NUMBER = is_present("c.p -> 'dossier_number'")
_DOC_CUT = _cut("d", "doc_fields")
_SUBJECT_CUT = _cut("t", "subject_fields")

# ``asked``: the dossiers in their order; ``member_docs``: the documents PART_OF each,
# directly or through one of its cases, once per edge; ``signals``: the few fields of each
# document, from ``lg_document_light`` (``schema.DOCUMENT_LIGHT_PROPS``), which does not read
# its props and their text, else from its props cut down once (``cut``); ``subjects``: the
# activities and decisions ABOUT each, from their props cut down once.
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
    SELECT d.id, coalesce(
        (SELECT l.props FROM lg_document_light l WHERE l.id = d.id), {_DOC_CUT}
    ) AS p
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
        SELECT coalesce(json_agg(k.kind ORDER BY k.kind NULLS FIRST), '[]'::json)
        FROM (
            SELECT DISTINCT f.kind
            FROM (
                SELECT x.kind
                FROM {COLLECTION_DOSSIERS} ds
                CROSS JOIN LATERAL {_kinds("ds.props -> 'case_kinds'")} AS x(kind)
                WHERE ds.id = a.dossier_id
                UNION ALL
                SELECT lg_str(cs.props -> 'kind')
                FROM own_cases o
                JOIN {COLLECTION_CASES} cs ON cs.id = o.case_id
                WHERE o.ord = a.ord
                UNION ALL
                SELECT x.kind
                FROM member_docs m
                JOIN signals s ON s.id = m.doc_id
                CROSS JOIN LATERAL {_kinds("s.signal -> 'case_kinds'")} AS x(kind)
                WHERE m.ord = a.ord
            ) f
            WHERE f.kind IS NOT NULL
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
            ) ORDER BY lg_str(s.date) NULLS FIRST, s.id
        ), '[]'::json)
        FROM signals s
        WHERE s.id IN (SELECT m.doc_id FROM member_docs m WHERE m.ord = a.ord)
    ) AS docs,
    (
        SELECT coalesce(json_agg(json_build_object(
            'kind', n.p -> 'kind',
            'date', n.p -> 'date',
            'status', n.p -> 'status'
        ) ORDER BY lg_str(n.p -> 'date') NULLS FIRST, n.id), '[]'::json)
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
        ) ORDER BY lg_str(n.p -> 'date') NULLS FIRST, n.id), '[]'::json)
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


def dossier_signals_bind(dossier_ids: list[str]) -> dict[str, Any]:
    """The parameters of ``_DOSSIER_SIGNALS_SQL`` for *dossier_ids*."""
    return {
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


def dossier_signals(store: Store, dossier_ids: list[str]) -> Iterator[dict[str, Any]]:
    """Documents, activities and decisions per dossier of *dossier_ids*; its case kinds
    (the ``Zaak.Soort`` of its own zaken: those ``PART_OF`` it, those of its documents that
    belong to it alone, and those rolled up from its activities); and the ``opened_on`` it
    holds.

    Only the few fields that are used are read, from props cut down once per node: a TK
    document holds its text and its payload. ``case_kinds`` is a set to its readers;
    sorted, it is the same list every time.
    """
    return store.query(_DOSSIER_SIGNALS_SQL, dossier_signals_bind(dossier_ids))


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

# ``name``: ``full_name OR name``; ``factions``: the ``faction_key`` of every membership once,
# sorted, null for one without (none when the memberships are no array).
_IDENTITIES_SQL = f"""
SELECT c.key,
       c.p -> 'family_name' AS family_name,
       {truthy_or("c.p -> 'full_name'", "c.p -> 'name'")} AS name,
       c.p -> 'initials' AS initials,
       c.p -> 'birth_date' AS birth_date,
       (
           SELECT coalesce(json_agg(k.faction ORDER BY k.faction NULLS FIRST), '[]'::json)
           FROM (
               SELECT DISTINCT lg_str(f.x -> 'faction_key') AS faction
               FROM json_array_elements({array_or_empty("c.memberships")}) AS f(x)
           ) k
       ) AS factions
FROM (
    SELECT m.key, m.pj_faction_memberships AS memberships, {_MEMBER_CUT} AS p
    FROM {COLLECTION_MEMBERS} m
    WHERE %(tk)s = ANY(m.labels)
    OFFSET 0
) c
WHERE {is_present("c.p -> 'family_name'")}
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


# The first and the last date of a group of signatures.
_FIRST_LAST = "to_json(min(x.date)) AS first, to_json(max(x.date)) AS last"

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
    SELECT m.key, m.p, d.pj_actors AS actors, d.date,
           lg_str(e.doc -> 'meta' -> 'function') AS function
    FROM {COLLECTION_EDGES} e
    JOIN tk_members m ON m.id = e.from_id
    JOIN {COLLECTION_DOCUMENTS} d ON d.id = e.to_id
    WHERE e.relation = %(authored)s
      AND e.from_collection = '{COLLECTION_MEMBERS}'
      AND lg_str(e.doc -> 'meta' -> 'capacity') = %(government)s
      AND d.date IS NOT NULL
)"""

# Per signature, every actor of the document that is the person (``person_id`` equal to
# their ``external_id``, null equal to null) with a name.
_SIGNATURES_SQL = f"""
WITH {_SIGNED}
SELECT x.key, to_json(x.name) AS name, to_json(x.function) AS function, {_FIRST_LAST}
FROM (
    SELECT s.key, s.function, s.date, lg_str(a.v -> 'name') AS name
    FROM signed s
    CROSS JOIN LATERAL json_array_elements({array_or_empty("s.actors")}) AS a(v)
    WHERE {is_absent("s.p -> 'family_name'")}
      AND coalesce((a.v -> 'person_id')::jsonb, 'null')
          = coalesce((s.p -> 'external_id')::jsonb, 'null')
) x
WHERE x.name IS NOT NULL
GROUP BY x.key, x.name, x.function
ORDER BY x.key, x.name NULLS FIRST, x.function NULLS FIRST
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


# ``month``: the first seven characters of the date.
_BY_MONTH_SQL = f"""
WITH {_SIGNED}
SELECT x.key, to_json(x.function) AS function, {_FIRST_LAST}
FROM (SELECT s.key, s.function, s.date, left(s.date, 7) AS month FROM signed s) x
GROUP BY x.key, x.function, x.month
ORDER BY x.key, x.function NULLS FIRST, x.month NULLS FIRST
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
    WHERE {is_present("props -> 'government_functions'")}
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
    return removals.remove_nodes(store, COLLECTION_MEMBERS, keys)


def faction_names(store: Store) -> Iterator[dict[str, Any]]:
    """``{key, name, abbreviation, aliases}`` of every faction (``normalize rijksoverheid``
    finds the faction of a bewindspersoon's party by them)."""
    statement = f"""
    SELECT key, props -> 'name' AS name, props -> 'abbreviation' AS abbreviation,
           props -> 'aliases' AS aliases
    FROM {COLLECTION_FACTIONS}
    WHERE lg_str(props -> 'chamber') IS DISTINCT FROM '{CHAMBER_EK}'
    ORDER BY key COLLATE "C"
    """
    return store.query(statement)


# The factions and committees of the Eerste Kamer, its members, and the MEMBER_OF edges
# into those factions and committees: per target (the factions, then the committees), by
# edge key.
_EK_COMPOSITION_SQL = f"""
WITH ek_factions AS (
    SELECT key, props FROM {COLLECTION_FACTIONS} WHERE lg_str(props -> 'chamber') = '{CHAMBER_EK}'
),
ek_committees AS (
    SELECT key, props FROM {COLLECTION_COMMITTEES} WHERE lg_str(props -> 'chamber') = '{CHAMBER_EK}'
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


# Fewer votes than a roll call of the Tweede Kamer can hold (150, a few absent): a decision
# read as a roll call before a faction vote with members voting apart was told from one.
MIXED_VOTES_BELOW = 100


def mixed_vote_decisions(store: Store, limit: int | None = None) -> list[str]:
    """The TK ``Besluit_Id`` of the decisions taken for a roll call (``vote_kind``
    ``member``) with fewer than ``MIXED_VOTES_BELOW`` votes, in key order: faction votes in
    which a few members voted apart, whose faction rows were left out. Normalized again
    they are faction votes, so a next slice no longer finds them."""
    return [
        str(row)
        for row in store.query(
            f"""
            SELECT lg_str(d.props -> 'decision_id')
            FROM {COLLECTION_DECISIONS} d
            WHERE lg_str(d.props -> 'vote_kind') = 'member'
              AND lg_str(d.props -> 'decision_id') IS NOT NULL
              AND (SELECT count(*) FROM {COLLECTION_EDGES} e
                   WHERE e.to_id = d.id AND e.relation = %(voted)s) < %(below)s
            ORDER BY d.key
            LIMIT %(limit)s
            """,
            {"voted": RELATION_VOTED, "below": MIXED_VOTES_BELOW, "limit": limit},
        )
    ]
