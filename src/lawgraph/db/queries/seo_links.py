"""The sources a page of a readable address links to by the edges of its node (``api/seo``):
per relation and direction the first ``LINKS`` nodes of one collection, by the covering
indexes of the edges, each read light and only when its own page is indexed (a page links
no page a search engine is told to leave out).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ACTIVITIES,
    COLLECTION_ARTICLES,
    COLLECTION_CASES,
    COLLECTION_COMMITMENTS,
    COLLECTION_DOCUMENTS,
    COLLECTION_EDGES,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    COLLECTION_MEMBERS,
    RELATION_MADE_IN,
)
from lawgraph.core.bwb_xml import KIND_PUBLICATION
from lawgraph.core.tk_records.kinds import KIND_AMENDMENT, KIND_MOTION
from lawgraph.db import GraphStore
from lawgraph.db.queries import member_role
from lawgraph.db.queries.instrument_scope import (
    is_staatsblad_law,
    law_column,
    law_of_article,
)

# The sources of one kind a page links at most.
LINKS = 20

# Whether the page of a paper ``d`` with its light row ``l`` is indexed: its text is in the
# data, or it is a motion or an amendment with its dictum (``api/seo/pages/parliament
# .document_indexed``).
DOCUMENT_INDEXED = f"""(lg_bool(l.props -> 'has_text')
    OR ((starts_with(lower(coalesce(d.kind, '')), '{KIND_MOTION.lower()}')
         OR starts_with(lower(coalesce(d.kind, '')), '{KIND_AMENDMENT.lower()}'))
        AND nullif(btrim(lg_str(l.props -> 'dictum')), '') IS NOT NULL))"""


@dataclass(frozen=True)
class Link:
    """The edges of *relation* from the node (``out``) or to it, whose other end is a node
    of *collection*."""

    relation: str
    collection: str
    out: bool = True


def linked(
    store: GraphStore, node_id: str, links: Sequence[Link], limit: int = LINKS
) -> dict[Link, list[dict[str, Any]]]:
    """Per link the nodes at the other end whose page is indexed, light (``light``): the
    first *limit* edges of each, in the order of their keys (``edges_from_cover``,
    ``edges_to_cover``); one statement for the edges, one per collection for the nodes."""
    if not links:
        return {}
    params: dict[str, Any] = {"id": node_id, "limit": limit}
    branches = []
    for n, link in enumerate(links):
        params[f"r{n}"], params[f"c{n}"] = link.relation, link.collection
        near, far = ("from", "to") if link.out else ("to", "from")
        branches.append(
            f"""(SELECT {n} AS n, e.{far}_id AS id FROM {COLLECTION_EDGES} e
                 WHERE e.{near}_id = %(id)s AND e.relation = %(r{n})s
                   AND e.{far}_collection = %(c{n})s
                 ORDER BY e.key LIMIT %(limit)s)"""
        )
    ends = list(store.query(" UNION ALL ".join(branches), params))
    by_collection: dict[str, set[str]] = {}
    for end in ends:
        by_collection.setdefault(links[end["n"]].collection, set()).add(end["id"])
    nodes = {
        row["id"]: row
        for collection, ids in by_collection.items()
        for row in light(store, collection, sorted(ids))
    }
    found: dict[Link, list[dict[str, Any]]] = {link: [] for link in links}
    for end in ends:
        if end["id"] in nodes and end["id"] != node_id:
            found[links[end["n"]]].append(nodes[end["id"]])
    return found


def grouped(
    store: GraphStore,
    node_id: str,
    groups: Mapping[str, Sequence[Link]],
    limit: int = LINKS,
) -> dict[str, list[dict[str, Any]]]:
    """``linked`` per group of links (a section of a page): each node once, at most
    *limit*."""
    found = linked(
        store,
        node_id,
        list(dict.fromkeys(link for links in groups.values() for link in links)),
        limit,
    )
    out: dict[str, list[dict[str, Any]]] = {}
    for name, links in groups.items():
        nodes = {row["id"]: row for link in links for row in found[link]}
        out[name] = list(nodes.values())[:limit]
    return out


def light(store: GraphStore, collection: str, ids: list[str]) -> list[dict[str, Any]]:
    """The nodes *ids* of *collection* whose page is indexed, light, with their
    ``collection``: what their name and readable address are made of
    (``api/seo/pages/base.source_link``). None of a collection without a reader."""
    read = _READERS.get(collection)
    if read is None or not ids:
        return []
    return [
        {**row, "collection": collection}
        for row in store.query(read, {"ids": ids, "publication": KIND_PUBLICATION})
    ]


# Per collection the light read of nodes by id whose page is indexed: of a paper one with
# a text or a dictum (``DOCUMENT_INDEXED``), of a judgment one
# that is no stub, of an article one with a text, of a law one that is no stub or
# publication (an EU act with an article), of a member one with a role, of a zaak one that is no motion or amendment, of an activity one with something made in it, of a commitment one with a
# text (``api/seo/pages``, ``db/queries/sitemaps``).
_READERS: dict[str, str] = {
    COLLECTION_DOCUMENTS: f"""
        SELECT d.id, d.kind, l.props AS light, d.pj_subject AS subject
        FROM {COLLECTION_DOCUMENTS} d
        JOIN lg_document_light l ON l.id = d.id
        WHERE d.id = ANY(%(ids)s::text[]) AND {DOCUMENT_INDEXED}
    """,
    COLLECTION_JUDGMENTS: """
        SELECT l.id, l.props AS light
        FROM lg_judgment_light l
        WHERE l.id = ANY(%(ids)s::text[]) AND lg_bool(l.props -> 'stub') IS NOT TRUE
    """,
    COLLECTION_ARTICLES: f"""
        SELECT a.id, a.bwb_id, a.celex, a.official_id, a.article_number,
               (SELECT coalesce(lg_str(i.props -> 'short_title'), i.citation_title)
                FROM {COLLECTION_INSTRUMENTS} i
                WHERE {law_of_article("i", "a")}
                ORDER BY i.key LIMIT 1) AS law
        FROM {COLLECTION_ARTICLES} a
        WHERE a.id = ANY(%(ids)s::text[]) AND a.stub IS NOT TRUE
          AND a.article_number IS NOT NULL
          AND nullif(btrim(lg_str(a.props -> 'text')), '') IS NOT NULL
    """,
    COLLECTION_INSTRUMENTS: f"""
        SELECT i.id, json_build_object(
                   'bwb_id', i.bwb_id, 'celex', i.celex,
                   'citation_title', i.citation_title,
                   'short_title', lg_str(i.props -> 'short_title'),
                   'title', lg_str(i.props -> 'title')) AS props
        FROM {COLLECTION_INSTRUMENTS} i
        WHERE i.id = ANY(%(ids)s::text[]) AND i.stub IS NOT TRUE
          AND i.kind IS DISTINCT FROM %(publication)s
          AND (i.bwb_id IS NOT NULL
               OR {is_staatsblad_law("i")}
               OR EXISTS (SELECT 1 FROM {COLLECTION_ARTICLES} a
                          WHERE a.celex = i.celex AND a.stub IS NOT TRUE))
    """,
    COLLECTION_MEMBERS: f"""
        SELECT m.id,
               coalesce(lg_str(m.props -> 'name'), lg_str(m.props -> 'display_name'))
                   AS name,
               lg_str(m.props -> 'slug') AS slug
        FROM {COLLECTION_MEMBERS} m
        WHERE m.id = ANY(%(ids)s::text[]) AND lg_str(m.props -> 'slug') IS NOT NULL
          AND {member_role.has_role("m")}
    """,
    COLLECTION_CASES: f"""
        SELECT c.id, c.key, json_build_object(
                   'number', lg_str(c.props -> 'number'),
                   'title', lg_str(c.props -> 'title'),
                   'citation_title', lg_str(c.props -> 'citation_title'),
                   'kind', lg_str(c.props -> 'kind')) AS props
        FROM {COLLECTION_CASES} c
        WHERE c.id = ANY(%(ids)s::text[])
          AND NOT starts_with(coalesce(lg_str(c.props -> 'kind'), ''), '{KIND_MOTION}')
          AND NOT starts_with(coalesce(lg_str(c.props -> 'kind'), ''), '{KIND_AMENDMENT}')
    """,
    COLLECTION_ACTIVITIES: f"""
        SELECT a.id, a.key, json_build_object(
                   'number', lg_str(a.props -> 'number'),
                   'kind', lg_str(a.props -> 'kind'),
                   'date', lg_str(a.props -> 'date'),
                   'agenda_title', lg_str(a.props -> 'agenda_title')) AS props
        FROM {COLLECTION_ACTIVITIES} a
        WHERE a.id = ANY(%(ids)s::text[])
          AND EXISTS (SELECT 1 FROM {COLLECTION_EDGES} e
                      WHERE e.to_id = a.id AND e.relation = '{RELATION_MADE_IN}'
                        AND e.from_collection IN ('{COLLECTION_DOCUMENTS}',
                                                  '{COLLECTION_COMMITMENTS}'))
    """,
    COLLECTION_COMMITMENTS: f"""
        SELECT c.id, c.key, json_build_object(
                   'number', c.number, 'text', lg_str(c.props -> 'text')) AS props
        FROM {COLLECTION_COMMITMENTS} c
        WHERE c.id = ANY(%(ids)s::text[]) AND lg_str(c.props -> 'text') IS NOT NULL
    """,
}


def neighbors(
    store: GraphStore, props: dict[str, Any], count: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The *count* articles of the same law before and after the article of *props* in the
    law's order (``position``), those its law lists (``seo.law``) with a text: the nearest
    first before it, then after it. None without a position."""
    column = law_column(props)
    position = props.get("position")
    if not props.get(column) or not isinstance(position, int | float):
        return [], []
    sides = []
    for before in (True, False):
        sign, order = ("<", "DESC") if before else (">", "ASC")
        sides.append(
            list(
                store.query(
                    f"""
                    SELECT a.id, a.bwb_id, a.celex, a.official_id, a.article_number
                    FROM {COLLECTION_ARTICLES} a
                    WHERE a.{column} = %(law)s AND a.position {sign} %(position)s
                      AND a.repealed IS NOT TRUE AND a.stub IS NOT TRUE
                      AND a.article_number IS NOT NULL
                      AND nullif(btrim(lg_str(a.props -> 'text')), '') IS NOT NULL
                    ORDER BY a.position {order}, a.key {order}
                    LIMIT %(count)s
                    """,
                    {"law": props[column], "position": position, "count": count},
                )
            )
        )
    return sides[0], sides[1]
