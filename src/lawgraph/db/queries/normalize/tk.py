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


def dossier_signals(store: Store, dossier_ids: list[str]) -> Iterator[dict[str, Any]]:
    """Documents, activities and decisions per dossier of *dossier_ids*; its case kinds
    (the ``Zaak.Soort`` of its own zaken: those ``PART_OF`` it, those of its papers that
    belong to it alone, and those rolled up from its activities); and the ``opened_on`` it
    holds.

    Every subquery returns the few fields that are used: a list of whole documents (their
    text, their payload) is built in the memory of the server before it is projected.
    """
    signal = """{
                            id: doc._id,
                            kind: doc.props.kind,
                            date: doc.props.date,
                            title: NOT_NULL(doc.props.dossier_title, doc.props.title,
                                            doc.props.display_name),
                            case_kinds: LENGTH(doc.props.dossier_numbers) == 1
                                ? doc.props.case_kinds : [],
                            own: doc.props.dossier_number != null
                                ? [doc.props.dossier_number, doc.props.dossier_suffix]
                                : null,
                            sequence: doc.props.sequence
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
            LET own_cases = (
                FOR e IN {COLLECTION_EDGES}
                    FILTER e._to == dossier_id AND e.relation == @part_of
                    FILTER STARTS_WITH(e._from, '{COLLECTION_CASES}/')
                    RETURN e._from
            )
            LET via_case = (
                FOR case_id IN own_cases
                    FOR e2 IN {COLLECTION_EDGES}
                        FILTER e2._to == case_id AND e2.relation == @part_of
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
                        passed: node.props.passed,
                        decision_kind: node.props.decision_kind,
                        decision_text: node.props.decision_text,
                        case_kind: node.props.primary_case_kind
                    }}
            )
            LET stored = DOCUMENT(dossier_id).props
            RETURN {{
                dossier_id: dossier_id,
                opened_on: stored.opened_on,
                case_kinds: UNIQUE(FLATTEN([
                    stored.case_kinds OR [],
                    own_cases[* RETURN DOCUMENT(CURRENT).props.kind],
                    APPEND(direct, via_case)[*].case_kinds
                ], 2)[* FILTER CURRENT != null]),
                docs: (
                    FOR doc IN UNIQUE(APPEND(direct, via_case))
                        RETURN UNSET(doc, "id", "case_kinds")
                ),
                activities: (
                    FOR node IN subjects
                        FILTER STARTS_WITH(node.id, '{COLLECTION_ACTIVITIES}/')
                        RETURN {{kind: node.kind, date: node.date, status: node.status}}
                ),
                decisions: (
                    FOR node IN subjects
                        FILTER STARTS_WITH(node.id, '{COLLECTION_DECISIONS}/')
                        RETURN UNSET(node, "id", "status")
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
