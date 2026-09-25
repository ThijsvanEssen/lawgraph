"""Queries behind ``semantic tk-government``: who made a commitment, who brought a dossier
in, and the cabinet in office then."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_CABINETS,
    COLLECTION_CASES,
    COLLECTION_COMMITMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_EDGES,
    COLLECTION_MEMBERS,
    RELATION_AUTHORED,
    RELATION_PART_OF,
)
from lawgraph.core.tk_records import CAPACITY_GOVERNMENT, CAPACITY_MEMBER
from lawgraph.db.counting import Store

# The role of the one who signs a document first.
ROLE_FIRST_SIGNATORY = "Eerste ondertekenaar"


def government_people(store: Store) -> Iterator[dict[str, Any]]:
    """Every member who held a post in a cabinet: ``{id, name, posts}``, ``id`` the member
    key, ``name`` the name Wikidata gives (else their own), ``posts`` their
    ``government_functions``."""
    aql = f"""
    FOR m IN {COLLECTION_MEMBERS}
        FILTER LENGTH(m.props.government_functions) > 0
        RETURN {{
            id: m._key,
            name: m.props.wikidata_name OR m.props.name,
            posts: m.props.government_functions
        }}
    """
    return store.query(aql)


def cabinet_periods(store: Store) -> Iterator[dict[str, Any]]:
    """``{key, from_date, to_date}`` of every cabinet."""
    aql = f"""
    FOR c IN {COLLECTION_CABINETS}
        RETURN {{ key: c._key, from_date: c.props.from_date, to_date: c.props.to_date }}
    """
    return store.query(aql)


def commitment_makers(store: Store) -> Iterator[dict[str, Any]]:
    """``{key, name, role, date, props}`` of every commitment: who made it as the source
    writes it, and what is stored now of who made it."""
    aql = f"""
    FOR c IN {COLLECTION_COMMITMENTS}
        RETURN {{
            key: c._key,
            name: c.props.minister_name,
            role: c.props.minister_role,
            date: c.props.made_on,
            props: KEEP(c.props, "member_key", "post", "ministry", "cabinet")
        }}
    """
    return store.query(aql)


# The first signature of the earliest document of a dossier (directly or through a case)
# that a Kamerlid or a bewindspersoon signed first.
_FIRST_SIGNATURES_AQL = f"""
FOR dossier IN {COLLECTION_DOSSIERS}
  LET papers = UNION_DISTINCT(
    (FOR p IN {COLLECTION_EDGES}
      FILTER p._to == dossier._id AND p.relation == @part_of
      FILTER NOT STARTS_WITH(p._from, "{COLLECTION_CASES}/")
      RETURN p._from),
    (FOR c IN {COLLECTION_EDGES}
      FILTER c._to == dossier._id AND c.relation == @part_of
      FILTER STARTS_WITH(c._from, "{COLLECTION_CASES}/")
      FOR p IN {COLLECTION_EDGES}
        FILTER p._to == c._from AND p.relation == @part_of
        RETURN p._from)
  )
  LET first = FIRST(
    FOR document_id IN papers
      FOR a IN {COLLECTION_EDGES}
        FILTER a._to == document_id AND a.relation == @authored
        FILTER a.meta.role == @first_role AND a.meta.capacity IN @capacities
        LET date = DOCUMENT(document_id).props.date
        FILTER date != null
        SORT date ASC, document_id ASC
        LIMIT 1
        RETURN {{
          date: date,
          member: PARSE_IDENTIFIER(a._from).key,
          capacity: a.meta.capacity,
          function: a.meta.function
        }}
  )
  RETURN {{
    key: dossier._key,
    first: first,
    props: KEEP(dossier.props, "ministry", "initiative", "cabinet")
  }}
"""


def dossier_first_signatures(store: Store) -> Iterator[dict[str, Any]]:
    """``{key, first, props}`` of every dossier: ``first`` the first signature of its
    earliest document signed first by a Kamerlid or a bewindspersoon (``{date, member,
    capacity, function}``, null when there is none), ``props`` what is stored now."""
    return store.query(
        _FIRST_SIGNATURES_AQL,
        {
            "part_of": RELATION_PART_OF,
            "authored": RELATION_AUTHORED,
            "first_role": ROLE_FIRST_SIGNATORY,
            "capacities": [CAPACITY_MEMBER, CAPACITY_GOVERNMENT],
        },
    )
