"""The neighbours that every one of several nodes has: what two sources share (6:162 BW and
7:658 BW; 6:162 BW and 51f Sv with the judgments that cite both)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from lawgraph.config.constants import COLLECTION_JUDGMENTS
from lawgraph.core.models import TYPE_OF_COLLECTION
from lawgraph.db import GraphStore
from lawgraph.db.queries.nodes import NO_FILTER, NeighborFilter, NodeSort, light_nodes

# The most nodes a request names: the edges of each are read whole.
MAX_SOURCES = 5

# How often a neighbour is cited, whichever table it is in; the other collections have no
# measure and keep to key order.
_CITED = (
    "coalesce(j.inbound_citation_count, a.inbound_citation_count,"
    " lg_num(i.props -> 'inbound_citation_count'))"
)


@dataclass(frozen=True)
class SharedFilter:
    """What narrows the shared neighbours: the edges (``edges``) and, of the judgments among
    them, their ``tiers`` and main ``area`` of law (``lg_subject_areas``)."""

    edges: NeighborFilter = NO_FILTER
    tiers: tuple[str, ...] = ()
    area: str | None = None


@dataclass
class SharedLink:
    """The edge by which a shared neighbour hangs at one of the nodes asked for."""

    source: str
    edge_id: str
    relation: str | None
    direction: str
    status: str | None
    confidence: float | None


@dataclass
class SharedNeighbor:
    doc: dict[str, Any]
    links: list[SharedLink]


@dataclass
class SharedBucket:
    collection: str
    total: int
    next_offset: int | None
    entries: list[SharedNeighbor]


@dataclass
class SharedNeighbors:
    buckets: list[SharedBucket]
    # per facet (``collection``, ``tier``, ``subject_area``) the values with their counts
    facets: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


def _statement(filters: SharedFilter, importance: bool) -> str:
    edges = filters.edges
    order = (
        "m.cited DESC NULLS LAST, m.id NULLS LAST" if importance else "m.id NULLS LAST"
    )
    tier = "(m.tier = ANY(%(tiers)s))" if filters.tiers else "TRUE"
    area = "(%(area)s::text = ANY(m.areas))" if filters.area else "TRUE"
    judgment = f"m.collection = '{COLLECTION_JUDGMENTS}'"
    return f"""
    WITH touching AS MATERIALIZED (
        SELECT s.ord, t.other, t.collection, t.edge, t.direction
        FROM unnest(%(ids)s::text[]) WITH ORDINALITY AS s(id, ord)
        CROSS JOIN LATERAL ({edges.touching_sql("s.id")}) t
        WHERE t.other <> ALL(%(ids)s::text[]) AND t.collection = ANY(%(known)s)
    ),
    -- the nodes at all of the sources
    shared AS MATERIALIZED (
        SELECT t.other AS id, t.collection FROM touching t
        GROUP BY t.other, t.collection
        HAVING count(DISTINCT t.ord) = cardinality(%(ids)s::text[])
    ),
    measured AS MATERIALIZED (
        SELECT s.id, s.collection, j.tier, lg_subject_areas(j.subjects) AS areas,
               {_CITED} AS cited
        FROM shared s
        LEFT JOIN judgments j ON s.collection = '{COLLECTION_JUDGMENTS}' AND j.id = s.id
        LEFT JOIN articles a ON s.collection = 'articles' AND a.id = s.id
        LEFT JOIN instruments i ON s.collection = 'instruments' AND i.id = s.id
    ),
    kept AS MATERIALIZED (
        SELECT * FROM measured m
        WHERE NOT ({judgment}) OR ({tier} AND {area})
    ),
    ranked AS (
        SELECT m.id, m.collection,
               row_number() OVER (PARTITION BY m.collection ORDER BY {order}) AS pos
        FROM kept m
    ),
    page AS (
        SELECT r.id, r.collection, r.pos FROM ranked r
        WHERE r.pos > %(offset)s AND r.pos <= %(offset)s + %(limit)s
    ),
    -- the edges of each node of the page, read once for the whole page
    links AS (
        SELECT p.id, json_agg(json_build_object(
                   'ord', t.ord, 'edge', e.key, 'relation', e.relation,
                   'direction', t.direction, 'status', e.status,
                   'confidence', e.confidence) ORDER BY t.ord NULLS LAST, e.key NULLS LAST) AS links
        FROM page p
        JOIN touching t ON t.other = p.id
        JOIN edges e ON e.key = t.edge
        GROUP BY p.id
    )
    SELECT
        (SELECT coalesce(json_agg(json_build_object('value', f.value, 'count', f.n)
                                  ORDER BY f.n DESC NULLS LAST, f.value NULLS LAST), '[]'::json)
         FROM (SELECT m.collection AS value, count(*)::int AS n
               FROM measured m GROUP BY 1) f) AS collection,
        (SELECT coalesce(json_agg(json_build_object('value', f.value, 'count', f.n)
                                  ORDER BY f.n DESC NULLS LAST, f.value NULLS LAST), '[]'::json)
         FROM (SELECT m.tier AS value, count(*)::int AS n FROM measured m
               WHERE {judgment} AND {area} GROUP BY 1) f) AS tier,
        (SELECT coalesce(json_agg(json_build_object('value', f.value, 'count', f.n)
                                  ORDER BY f.n DESC NULLS LAST, f.value NULLS LAST), '[]'::json)
         FROM (SELECT u.area AS value, count(*)::int AS n FROM measured m
               CROSS JOIN LATERAL unnest(m.areas) AS u(area)
               WHERE {judgment} AND {tier} GROUP BY 1) f) AS subject_area,
        (SELECT coalesce(json_agg(json_build_object('collection', c.collection, 'total', c.n)
                                  ORDER BY c.collection NULLS LAST), '[]'::json)
         FROM (SELECT m.collection, count(*)::int AS n FROM kept m GROUP BY 1) c) AS totals,
        (SELECT coalesce(json_agg(json_build_object(
                    'id', p.id, 'collection', p.collection, 'links', l.links
                ) ORDER BY p.collection NULLS LAST, p.pos NULLS LAST), '[]'::json)
         FROM page p JOIN links l ON l.id = p.id) AS items
    """


def get_shared_neighbors(
    store: GraphStore,
    ids: list[str],
    *,
    filters: SharedFilter,
    sort: NodeSort = "importance",
    limit: int,
    offset: int = 0,
) -> SharedNeighbors:
    """The nodes at the other end of an edge of every node of *ids* (the nodes themselves
    left out), per collection, a page of *limit* from *offset* in each, the most cited first
    (``sort=importance``; judgments, articles and instruments, then by key) or by key.

    An edge counts in either direction (``filters.edges`` narrows relation, status, direction
    and collections); a neighbour carries every edge that ties it to each node. The
    ``tiers`` and ``area`` of the filter narrow the judgments alone. ``facets`` count the
    neighbours: per collection and, of the judgments, per tier (under the area) and per main
    area of law (under the tiers), each under the other filter.

    Reads the edges of each node once, through their covering indexes, and the rows of the
    neighbours it ranks or counts by key (``judgments``, ``articles``, ``instruments``).
    """
    params: dict[str, Any] = {
        "ids": ids,
        "known": sorted(TYPE_OF_COLLECTION),
        "tiers": list(filters.tiers),
        "area": filters.area,
        "limit": limit,
        "offset": offset,
        "collections": filters.edges.collections,
        **filters.edges.edge_params(),
    }
    rows = store.query(_statement(filters, sort == "importance"), params)
    row = next(iter(rows), None) or {}
    docs = light_nodes(store, [item["id"] for item in row.get("items") or []])
    by_collection: dict[str, list[SharedNeighbor]] = {}
    for item in row.get("items") or []:
        doc = docs.get(item["id"])
        if doc is None:
            continue
        by_collection.setdefault(item["collection"], []).append(
            SharedNeighbor(
                doc=doc,
                links=[
                    SharedLink(
                        source=ids[link["ord"] - 1],
                        edge_id=link["edge"],
                        relation=link["relation"],
                        direction=link["direction"],
                        status=link["status"],
                        confidence=link["confidence"],
                    )
                    for link in item["links"] or []
                ],
            )
        )
    end = offset + limit
    buckets = [
        SharedBucket(
            collection=bucket["collection"],
            total=bucket["total"],
            next_offset=end if end < bucket["total"] else None,
            entries=by_collection.get(bucket["collection"], []),
        )
        for bucket in row.get("totals") or []
    ]
    return SharedNeighbors(
        buckets=buckets,
        facets={
            name: list(row.get(name) or [])
            for name in ("collection", "tier", "subject_area")
        },
    )
