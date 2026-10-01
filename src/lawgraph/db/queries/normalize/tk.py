"""The graph reads of the normalize phase for the Tweede and Eerste Kamer and the
government: stored cases, dossiers and members, the signals of a dossier, the
government signatures and the composition of the Eerste Kamer."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

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
from lawgraph.core.tk_records import CAPACITY_GOVERNMENT
from lawgraph.db.counting import Store


def case_dossier_numbers(store: Store) -> Iterator[dict[str, Any]]:
    """``{id, dossier_numbers}`` of every case that names a dossier."""
    aql = f"""
    FOR case IN {COLLECTION_CASES}
        FILTER case.props.dossier_numbers != null
        RETURN {{id: case._id, dossier_numbers: case.props.dossier_numbers}}
    """
    return store.query(aql)


def nodes_by_external_id(
    store: Store, collection: str, names: list[str]
) -> Iterator[dict[str, Any]]:
    """``{key, id, props}`` of the nodes of *collection* with a TK ``Id``; the props only
    *names*."""
    aql = f"""
        FOR d IN {collection}
            FILTER d.props.external_id != null
            RETURN {{
                key: d._key,
                id: d.props.external_id,
                props: KEEP(d.props, @names)
            }}
        """
    return store.query(aql, {"names": names})


def faction_aliases(store: Store) -> Iterator[Any]:
    """Every alias a stored faction carries."""
    aql = f"""
        FOR faction IN {COLLECTION_FACTIONS}
            FOR alias IN faction.props.aliases || []
                RETURN DISTINCT alias
        """
    return store.query(aql)


def dossier_case_kinds(store: Store, keys: list[str]) -> Iterator[dict[str, Any]]:
    """``{key, case_kinds}`` of the dossiers with these *keys*."""
    lookup = f"""
        FOR dossier IN {COLLECTION_DOSSIERS}
            FILTER dossier._key IN @keys
            RETURN {{key: dossier._key, case_kinds: dossier.props.case_kinds}}
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
    ) AS decisions
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
    aql = f"""
        FOR dossier IN {COLLECTION_DOSSIERS}
            FILTER dossier.props.number IN @numbers
            RETURN {{
                key: dossier._key,
                number: dossier.props.number,
                same_number_count: dossier.props.same_number_count
            }}
        """
    return store.query(aql, {"numbers": numbers})


def member_identities(store: Store) -> Iterator[dict[str, Any]]:
    """``{key, family_name, name, initials, birth_date, factions}`` of every Tweede Kamer
    person with a surname (``normalize rijksoverheid`` matches the bewindspersonen to them):
    ``name`` the full name, ``factions`` the keys of the factions they sat in."""
    aql = f"""
    FOR m IN {COLLECTION_MEMBERS}
        FILTER @tk IN m.labels AND m.props.family_name != null
        RETURN {{
            key: m._key,
            family_name: m.props.family_name,
            name: m.props.full_name OR m.props.name,
            initials: m.props.initials,
            birth_date: m.props.birth_date,
            factions: SORTED_UNIQUE(m.props.faction_memberships[*].faction_key)
        }}
    """
    return store.query(aql, {"tk": CHAMBER_TK})


def government_signatures(store: Store) -> Iterator[dict[str, Any]]:
    """The signatures as a minister or state secretary of the Tweede Kamer persons without a
    name of their own (a minister who never sat in parliament): ``{key, name, function,
    first, last}`` per person, signed name and function, with the first and last date."""
    aql = f"""
    FOR e IN {COLLECTION_EDGES}
        FILTER e.relation == @authored AND e.meta.capacity == @government
        LET m = DOCUMENT(e._from)
        FILTER m.props.family_name == null AND @tk IN m.labels
        LET d = DOCUMENT(e._to)
        FILTER d.props.date != null
        FOR a IN (d.props.actors OR [])
            FILTER a.person_id == m.props.external_id AND a.name != null
            COLLECT key = m._key, name = a.name, function = e.meta.function
                AGGREGATE first = MIN(d.props.date), last = MAX(d.props.date)
            RETURN {{key, name, function, first, last}}
    """
    return store.query(
        aql,
        {
            "authored": RELATION_AUTHORED,
            "government": CAPACITY_GOVERNMENT,
            "tk": CHAMBER_TK,
        },
    )


def government_signatures_by_month(store: Store) -> Iterator[dict[str, Any]]:
    """The signatures as a minister or state secretary of every Tweede Kamer person:
    ``{key, function, first, last}`` per person, function and month."""
    aql = f"""
    FOR e IN {COLLECTION_EDGES}
        FILTER e.relation == @authored AND e.meta.capacity == @government
        LET m = DOCUMENT(e._from)
        FILTER @tk IN m.labels
        LET d = DOCUMENT(e._to)
        FILTER d.props.date != null
        COLLECT key = m._key, function = e.meta.function,
                month = SUBSTRING(d.props.date, 0, 7)
            AGGREGATE first = MIN(d.props.date), last = MAX(d.props.date)
        RETURN {{key, function, first, last}}
    """
    return store.query(
        aql,
        {
            "authored": RELATION_AUTHORED,
            "government": CAPACITY_GOVERNMENT,
            "tk": CHAMBER_TK,
        },
    )


def labelled_members(store: Store, label: str) -> Iterator[str]:
    """The keys of the members with *label* (``Rijksoverheid``: a bewindspersoon only
    Rijksoverheid knows)."""
    aql = f"""
    FOR m IN {COLLECTION_MEMBERS}
        FILTER @label IN m.labels
        RETURN m._key
    """
    return store.query(aql, {"label": label})


def government_members(store: Store) -> Iterator[str]:
    """The keys of the members that have ``government_functions``."""
    aql = f"""
    FOR m IN {COLLECTION_MEMBERS}
        FILTER m.props.government_functions != null
        RETURN m._key
    """
    return store.query(aql)


def decisions_of_vote_records(
    store: Store, record_ids: list[str]
) -> Iterator[dict[str, Any]]:
    """``{key, decision_id}`` of the decisions the Stemming records *record_ids* voted on,
    by the VOTED edges they made: a vote the Kamer deleted names no decision any more."""
    aql = f"""
    FOR id IN @ids
        FOR e IN {COLLECTION_EDGES}
            FILTER id IN e.meta.record_ids[*] AND e.relation == @voted
            LET decision = DOCUMENT(e._to)
            FILTER decision != null
            RETURN DISTINCT {{key: decision._key, decision_id: decision.props.decision_id}}
    """
    return store.query(aql, {"ids": record_ids, "voted": RELATION_VOTED})


def remove_members(store: Store, keys: list[str]) -> int:
    """Remove the members *keys* with every edge at them; how many members went."""
    ids = [f"{COLLECTION_MEMBERS}/{key}" for key in keys]
    edges = f"""
    FOR id IN @ids
        FOR key IN UNION_DISTINCT(
            (FOR e IN {COLLECTION_EDGES} FILTER e._from == id RETURN e._key),
            (FOR e IN {COLLECTION_EDGES} FILTER e._to == id RETURN e._key)
        )
            REMOVE key IN {COLLECTION_EDGES}
    """
    list(store.query(edges, {"ids": ids}))
    members = f"""
    FOR key IN @keys
        REMOVE key IN {COLLECTION_MEMBERS} OPTIONS {{ ignoreErrors: true }}
        RETURN 1
    """
    return sum(store.query(members, {"keys": keys}))


def faction_names(store: Store) -> Iterator[dict[str, Any]]:
    """``{key, name, abbreviation, aliases}`` of every faction (``normalize rijksoverheid``
    finds the faction of a bewindspersoon's party by them)."""
    aql = f"""
    FOR f IN {COLLECTION_FACTIONS}
        FILTER f.props.chamber != "EK"
        RETURN {{
            key: f._key,
            name: f.props.name,
            abbreviation: f.props.abbreviation,
            aliases: f.props.aliases
        }}
    """
    return store.query(aql)


def ek_composition(store: Store) -> dict[str, Any]:
    """What the graph holds of the composition of the Eerste Kamer: its factions and
    committees (``chamber`` ``EK``) with their props, the members with an ``ek`` prop, and
    the ``MEMBER_OF`` edges into those factions and committees."""
    aql = f"""
    LET factions = (
        FOR f IN {COLLECTION_FACTIONS} FILTER f.props.chamber == "EK"
            RETURN {{ key: f._key, props: f.props }}
    )
    LET committees = (
        FOR c IN {COLLECTION_COMMITTEES} FILTER c.props.chamber == "EK"
            RETURN {{ key: c._key, props: c.props }}
    )
    LET members = (
        FOR m IN {COLLECTION_MEMBERS} FILTER m.props.ek != null
            RETURN {{ key: m._key, ek: m.props.ek }}
    )
    LET targets = APPEND(
        factions[* RETURN CONCAT("{COLLECTION_FACTIONS}/", CURRENT.key)],
        committees[* RETURN CONCAT("{COLLECTION_COMMITTEES}/", CURRENT.key)]
    )
    LET edges = (
        FOR id IN targets
            FOR e IN {COLLECTION_EDGES}
                FILTER e._to == id AND e.relation == @member_of
                RETURN {{ from: e._from, to: e._to, meta: e.meta }}
    )
    RETURN {{ factions, committees, members, edges }}
    """
    row = next(iter(store.query(aql, {"member_of": RELATION_MEMBER_OF})), None)
    return row or {"factions": [], "committees": [], "members": [], "edges": []}


def members_born_on(store: Store, dates: list[str]) -> Iterator[dict[str, Any]]:
    """``{key, family_name, birth_date}`` of the members born on one of *dates*."""
    aql = f"""
    FOR m IN {COLLECTION_MEMBERS}
        FILTER m.props.birth_date IN @dates
        RETURN {{
            key: m._key, family_name: m.props.family_name, birth_date: m.props.birth_date
        }}
    """
    return store.query(aql, {"dates": dates})
