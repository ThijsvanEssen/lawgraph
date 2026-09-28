"""The graph reads and updates of the normalize phase: what a normalize step reads back of
the nodes it or an earlier step wrote (article versions, stored Tweede Kamer nodes, the
signals of a dossier) and the short titles it sets in place."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import (
    CHAMBER_TK,
    COLLECTION_ACTIVITIES,
    COLLECTION_ARTICLE_VERSIONS,
    COLLECTION_ARTICLES,
    COLLECTION_CASES,
    COLLECTION_DECISIONS,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_EDGES,
    COLLECTION_FACTIONS,
    COLLECTION_INSTRUMENT_VERSIONS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    COLLECTION_MEMBERS,
    RELATION_ABOUT,
    RELATION_AUTHORED,
    RELATION_PART_OF,
)
from lawgraph.core.tk_records import CAPACITY_GOVERNMENT
from lawgraph.db.counting import Store

# ── BWB ──────────────────────────────────────────────────────────────────────


def update_abbreviations(store: Store, rows: list[dict[str, Any]]) -> int:
    """Set ``short_title`` and ``aliases`` on the instruments of *rows* (``{key,
    short_title, aliases}``) where either differs; how many changed. A null or empty
    value removes the prop."""
    aql = f"""
        FOR row IN @rows
            FOR inst IN {COLLECTION_INSTRUMENTS}
                FILTER inst._key == row.key
                LET aliases = LENGTH(row.aliases) > 0 ? row.aliases : null
                FILTER inst.props.short_title != row.short_title
                    OR inst.props.aliases != aliases
                UPDATE inst WITH {{
                    props: {{ short_title: row.short_title, aliases: aliases }}
                }} IN {COLLECTION_INSTRUMENTS} OPTIONS {{ keepNull: false }}
                RETURN 1
        """
    return len(list(store.query(aql, {"rows": rows})))


_ARTICLES_AQL = f"""
FOR a IN {COLLECTION_ARTICLES}
    FILTER a.props.bwb_id IN @ids
    RETURN {{key: a._key, bwb_id: a.props.bwb_id, stam_id: a.props.stam_id}}
"""

_VERSIONS_AQL = f"""
FOR v IN {COLLECTION_ARTICLE_VERSIONS}
    FILTER v.props.bwb_id IN @ids
    RETURN {{
        key: v._key,
        bwb_id: v.props.bwb_id,
        stam_id: v.props.stam_id,
        number: v.props.article_number,
        label: v.props.label,
        valid_from: v.props.valid_from,
        valid_until: v.props.valid_until,
        current: v.props.current,
        last_seen: v.props.last_seen,
        effect: v.props.effect,
        text_start: SUBSTRING(v.props.text, 0, 60),
        title: v.props.instrument_citation_title
    }}
"""


def article_identities(store: Store, bwb_ids: list[str]) -> Iterator[dict[str, Any]]:
    """``{key, bwb_id, stam_id}`` of the articles of *bwb_ids*."""
    return store.query(_ARTICLES_AQL, {"ids": bwb_ids})


def article_versions(store: Store, bwb_ids: list[str]) -> Iterator[dict[str, Any]]:
    """The article versions of *bwb_ids*, with their validity and article number."""
    return store.query(_VERSIONS_AQL, {"ids": bwb_ids})


def toestand_starts(store: Store, bwb_ids: list[str]) -> dict[str, list[str]]:
    """The start dates of the toestanden of each of *bwb_ids*, oldest first."""
    aql = f"""
    FOR v IN {COLLECTION_INSTRUMENT_VERSIONS}
        FILTER v.props.bwb_id IN @ids
        SORT v.props.valid_from
        COLLECT bwb_id = v.props.bwb_id INTO starts = v.props.valid_from
        RETURN {{ bwb_id, starts }}
    """
    return {
        row["bwb_id"]: [s for s in row["starts"] if s]
        for row in store.query(aql, {"ids": bwb_ids})
    }


# ── Tweede Kamer ─────────────────────────────────────────────────────────────


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


def dossier_signals(store: Store, dossier_ids: list[str]) -> Iterator[dict[str, Any]]:
    """Documents, activities and decisions per dossier of *dossier_ids*, and the case
    kinds, ``closed`` and ``opened_on`` it holds.

    Every subquery returns the few fields that are used: a list of whole documents (their
    text, their payload) is built in the memory of the server before it is projected.
    """
    signal = """{
                            id: doc._id,
                            kind: doc.props.kind,
                            date: doc.props.date,
                            title: (doc.props.title != null ? doc.props.title
                                    : doc.props.display_name)
                        }"""
    aql = f"""
        FOR dossier_id IN @dossier_ids
            LET direct = (
                FOR e IN {COLLECTION_EDGES}
                    FILTER e._to == dossier_id AND e.relation == @part_of
                    FILTER STARTS_WITH(e._from, '{COLLECTION_DOCUMENTS}/')
                    LET doc = DOCUMENT(e._from)
                    FILTER doc != null
                    RETURN {signal}
            )
            LET via_case = (
                FOR e1 IN {COLLECTION_EDGES}
                    FILTER e1._to == dossier_id AND e1.relation == @part_of
                    FILTER STARTS_WITH(e1._from, '{COLLECTION_CASES}/')
                    FOR e2 IN {COLLECTION_EDGES}
                        FILTER e2._to == e1._from AND e2.relation == @part_of
                        FILTER STARTS_WITH(e2._from, '{COLLECTION_DOCUMENTS}/')
                        LET doc = DOCUMENT(e2._from)
                        FILTER doc != null
                        RETURN {signal}
            )
            LET subjects = (
                FOR e IN {COLLECTION_EDGES}
                    FILTER e._to == dossier_id AND e.relation == @about
                    LET node = DOCUMENT(e._from)
                    FILTER node != null
                    RETURN {{
                        id: node._id,
                        kind: node.props.kind,
                        date: node.props.date,
                        status: node.props.status,
                        passed: node.props.passed
                    }}
            )
            LET stored = DOCUMENT(dossier_id).props
            RETURN {{
                dossier_id: dossier_id,
                closed: stored.closed,
                outcome: stored.outcome,
                opened_on: stored.opened_on,
                case_kinds: stored.case_kinds,
                docs: (
                    FOR doc IN UNIQUE(APPEND(direct, via_case))
                        RETURN UNSET(doc, "id")
                ),
                activities: (
                    FOR node IN subjects
                        FILTER STARTS_WITH(node.id, '{COLLECTION_ACTIVITIES}/')
                        RETURN {{kind: node.kind, date: node.date, status: node.status}}
                ),
                decisions: (
                    FOR node IN subjects
                        FILTER STARTS_WITH(node.id, '{COLLECTION_DECISIONS}/')
                        RETURN {{date: node.date, passed: node.passed}}
                )
            }}
        """
    bind = {"part_of": RELATION_PART_OF, "about": RELATION_ABOUT}
    return store.query(aql, {**bind, "dossier_ids": dossier_ids})


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
            factions: UNIQUE(m.props.faction_memberships[*].faction_key)
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


def remove_nodes_except(store: Store, collection: str, keep: list[str]) -> int:
    """Remove the nodes of *collection* whose key is not in *keep*, for a collection one
    pipeline derives in full; how many went."""
    aql = f"""
    FOR n IN {collection}
        FILTER n._key NOT IN @keep
        REMOVE n IN {collection}
        RETURN 1
    """
    return sum(store.query(aql, {"keep": keep}))


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
        RETURN {{
            key: f._key,
            name: f.props.name,
            abbreviation: f.props.abbreviation,
            aliases: f.props.aliases
        }}
    """
    return store.query(aql)


def remove_edges_except(store: Store, relation: str, keep: list[str]) -> int:
    """Remove the edges of *relation* whose key is not in *keep*; how many went. For edges
    one pipeline derives in full on every run, so an edge it no longer derives goes."""
    aql = f"""
    FOR e IN {COLLECTION_EDGES}
        FILTER e.relation == @relation AND e._key NOT IN @keep
        REMOVE e IN {COLLECTION_EDGES}
        RETURN 1
    """
    return sum(store.query(aql, {"relation": relation, "keep": keep}))


# ── Rechtspraak ──────────────────────────────────────────────────────────────


def translated_judgments(
    store: Store, rows: list[dict[str, Any]]
) -> Iterator[dict[str, Any]]:
    """The judgment each translation of *rows* translates: ``{key, original: {key, ecli,
    summary}}`` for every row (``{key, court_code, date, case_key}``) whose court gave, on
    that day and under that case number, a judgment with a Dutch summary."""
    aql = f"""
    FOR row IN @rows
        LET original = FIRST(
            FOR j IN {COLLECTION_JUDGMENTS}
                FILTER row.case_key IN j.props.case_number_keys[*]
                FILTER j.props.court_code == row.court_code
                FILTER j.props.date_eff == row.date
                FILTER j._key != row.key AND j.props.summary != null
                SORT j._key
                LIMIT 1
                RETURN {{key: j._key, ecli: j.props.ecli, summary: j.props.summary}}
        )
        FILTER original != null
        RETURN {{key: row.key, original: original}}
    """
    return store.query(aql, {"rows": rows})


def update_judgment_props(store: Store, rows: list[dict[str, Any]]) -> int:
    """Merge ``props`` into the judgment ``key`` of each of *rows*; how many changed."""
    aql = f"""
    FOR row IN @rows
        FOR j IN {COLLECTION_JUDGMENTS}
            FILTER j._key == row.key
            FILTER NOT MATCHES(j.props, row.props)
            UPDATE j WITH {{ props: row.props }} IN {COLLECTION_JUDGMENTS}
                OPTIONS {{ mergeObjects: true }}
            RETURN 1
    """
    return sum(store.query(aql, {"rows": rows}))
