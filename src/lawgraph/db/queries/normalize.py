"""The graph reads and updates of the normalize phase: what a normalize step reads back of
the nodes it or an earlier step wrote (article versions, stored Tweede Kamer nodes, the
signals of a dossier) and the short titles it sets in place."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ACTIVITIES,
    COLLECTION_ARTICLE_VERSIONS,
    COLLECTION_ARTICLES,
    COLLECTION_CASES,
    COLLECTION_DECISIONS,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_EDGES,
    COLLECTION_FACTIONS,
    COLLECTION_INSTRUMENTS,
    RELATION_ABOUT,
    RELATION_PART_OF,
)
from lawgraph.db.counting import Store

# ── BWB ──────────────────────────────────────────────────────────────────────


def update_short_titles(store: Store, rows: list[dict[str, Any]]) -> int:
    """Set ``short_title`` on the instruments of *rows* (``{key, short_title}``) whose
    short title differs; how many changed."""
    aql = f"""
        FOR row IN @rows
            FOR inst IN {COLLECTION_INSTRUMENTS}
                FILTER inst._key == row.key
                FILTER inst.props.short_title != row.short_title
                UPDATE inst WITH {{ props: {{ short_title: row.short_title }} }}
                    IN {COLLECTION_INSTRUMENTS} OPTIONS {{ keepNull: false }}
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
        valid_from: v.props.valid_from,
        valid_until: v.props.valid_until,
        title: v.props.instrument_citation_title
    }}
"""


def article_identities(store: Store, bwb_ids: list[str]) -> Iterator[dict[str, Any]]:
    """``{key, bwb_id, stam_id}`` of the articles of *bwb_ids*."""
    return store.query(_ARTICLES_AQL, {"ids": bwb_ids})


def article_versions(store: Store, bwb_ids: list[str]) -> Iterator[dict[str, Any]]:
    """The article versions of *bwb_ids*, with their validity and article number."""
    return store.query(_VERSIONS_AQL, {"ids": bwb_ids})


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
    """Documents, activities and decisions per dossier of *dossier_ids*, and the ``closed``
    and ``opened_on`` it holds.

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
                        passed: node.props.passed
                    }}
            )
            LET stored = DOCUMENT(dossier_id).props
            RETURN {{
                dossier_id: dossier_id,
                closed: stored.closed,
                opened_on: stored.opened_on,
                docs: (
                    FOR doc IN UNIQUE(APPEND(direct, via_case))
                        RETURN UNSET(doc, "id")
                ),
                activities: (
                    FOR node IN subjects
                        FILTER STARTS_WITH(node.id, '{COLLECTION_ACTIVITIES}/')
                        RETURN {{kind: node.kind, date: node.date}}
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
