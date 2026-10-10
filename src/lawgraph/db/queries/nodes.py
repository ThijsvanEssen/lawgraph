"""Node and neighborhood query helpers."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

from lawgraph.config.constants import COLLECTION_MEMBERS, RELATION_AUTHORED
from lawgraph.core.models import COLLECTION_OF_TYPE, TYPE_OF_COLLECTION
from lawgraph.db import GraphStore
from lawgraph.db._rows import (
    canvas_edge_doc,
    canvas_props,
    light_edge_doc,
    light_node_doc,
    light_props,
)
from lawgraph.db.queries._helpers import _extract_confidence
from lawgraph.db.store import (
    ReadTimedOut,
    read_time_left,
    reset_read_deadline,
    set_read_deadline,
)
from lawgraph.db.version_cache import lasting, stale_wait


class NodeNotFoundError(ValueError):
    """Raised when a requested node does not exist in the collection."""


class UnsupportedCollectionError(ValueError):
    """Raised when a collection name is not in the allowed set."""


Direction = Literal["outbound", "inbound"]
DIRECTIONS: tuple[Direction, ...] = ("outbound", "inbound")

# Every node collection can be explored: one per node type.
_ALLOWED_NODE_COLLECTIONS = frozenset(TYPE_OF_COLLECTION)

DEFAULT_BUCKET_LIMIT = 30

# The columns of an edge that hold the node itself and its neighbour, and the neighbour's
# collection, per direction.
_EDGE_SIDES: dict[Direction, tuple[str, str, str]] = {
    "outbound": ("from_id", "to_id", "to_collection"),
    "inbound": ("to_id", "from_id", "from_collection"),
}

# The columns of a node and an edge as the neighbourhood statement gives them, in order.
_NODE_FIELDS = ("id", "key", "type", "labels", "props")
_EDGE_FIELDS = ("key", "from_id", "to_id", "doc")


@dataclass(frozen=True)
class NeighborFilter:
    """Which edges of a node count: every field left as None lets everything through.

    ``node_types`` restricts the neighbours to these ``NodeType`` values, ``direction`` the
    edges to those that leave (``outbound``) or reach (``inbound``) the node.
    """

    relations: tuple[str, ...] | None = None
    node_types: tuple[str, ...] | None = None
    direction: Direction | None = None
    status: str | None = None

    @property
    def directions(self) -> tuple[Direction, ...]:
        return (self.direction,) if self.direction else DIRECTIONS

    @property
    def collections(self) -> list[str] | None:
        """The collections of ``node_types`` (one collection holds one type)."""
        if self.node_types is None:
            return None
        return [
            collection
            for node_type, collection in COLLECTION_OF_TYPE.items()
            if node_type.value in self.node_types
        ]

    def edge_sql(self, edge: str) -> str:
        """Conditions on the relation and status of ``edge``; binds ``relations``,
        ``status``."""
        conditions = []
        if self.relations is not None:
            conditions.append(f"AND {edge}.relation = ANY(%(relations)s)")
        if self.status is not None:
            conditions.append(f"AND {edge}.status = %(status)s")
        return " ".join(conditions)

    def edge_params(self) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if self.relations is not None:
            params["relations"] = list(self.relations)
        if self.status is not None:
            params["status"] = self.status
        return params


NO_FILTER = NeighborFilter()


@dataclass
class NeighborEntry:
    doc: dict[str, Any]
    edge: dict[str, Any]
    direction: Direction

    @property
    def relation(self) -> str | None:
        relation = self.edge.get("relation")
        return relation if isinstance(relation, str) else None

    @property
    def confidence(self) -> float | None:
        return _extract_confidence(self.edge)


@dataclass
class NeighborFacet:
    """The edges of a node that share a relation, a direction and a neighbour collection."""

    relation: str | None
    direction: Direction
    collection: str
    count: int


@dataclass
class NeighborBucket:
    """One facet with the page of its neighbours that was asked for."""

    facet: NeighborFacet
    next_offset: int | None
    entries: list[NeighborEntry]
    # of an article: per lid its edges cite, how many of the whole bucket do ("" no lid);
    # None where no edge of the bucket names a lid
    lid_counts: dict[str, int] | None = None
    # of a member's AUTHORED: per capacity they signed in, how many of the whole bucket
    # ("" none); None for every other bucket
    capacity_counts: dict[str, int] | None = None


@dataclass
class NodeGraphData:
    node: dict[str, Any]
    buckets: list[NeighborBucket]
    # of an article asked without waiting for its lid counts: they are being counted
    lid_counts_pending: bool = False


def _load_node(store: GraphStore, collection: str, key: str) -> dict[str, Any]:
    if collection not in _ALLOWED_NODE_COLLECTIONS:
        raise UnsupportedCollectionError("unsupported collection")
    node = store.get_document(collection, key)
    if node is None:
        raise NodeNotFoundError("node not found")
    return node


def _capacity_counts(store: GraphStore, member_id: str) -> dict[str, dict[str, int]]:
    """Per collection a member signed papers of (documents, cases, commitments): how many
    they signed in each capacity (``meta.capacity`` of AUTHORED: kamerlid, bewindspersoon,
    overig; "" none), every signature, from ``lg_authored`` through its index of members.
    Empty until the table is whole and dated (``member_authored``): the page then counts
    only what it holds."""
    from lawgraph.db.queries import member_authored

    if not (member_authored.is_filled(store) and member_authored.is_dated(store)):
        return {}
    counts: dict[str, dict[str, int]] = {}
    for row in store.query(
        """
        SELECT split_part(a.document_id, '/', 1) AS collection,
               coalesce(a.capacity, '') AS capacity, count(*)::int AS n
        FROM lg_authored a
        WHERE a.member_id = %(member)s
        GROUP BY 1, 2
        """,
        {"member": member_id},
    ):
        counts.setdefault(row["collection"], {})[row["capacity"]] = row["n"]
    return counts


def get_node_with_neighbors(
    store: GraphStore,
    collection: str,
    key: str,
    *,
    filters: NeighborFilter = NO_FILTER,
    limit: int = DEFAULT_BUCKET_LIMIT,
    offset: int = 0,
    canvas: bool = False,
    wait_for_lids: bool = True,
) -> NodeGraphData:
    """A node with its neighbours, in buckets of one relation, direction and collection.

    ``limit`` and ``offset`` page inside every bucket; a bucket says how many edges it has
    and where its next page starts. With *canvas* a neighbour has only the props and the
    edge ``meta`` the canvas of the explorer reads (``_rows.CANVAS_PROPS``). Without
    *wait_for_lids* an article's lid counts that are not kept yet are left out
    (``lid_counts_pending``) and counted on in the background, for the next request.
    """
    node = _load_node(store, collection, key)
    facets = _count_facets(store, node["_id"], filters)
    pages = _read_pages(store, node["_id"], filters, facets, limit, offset, canvas)
    lids: dict[tuple[str | None, str, str], dict[str, int]] | None = {}
    if collection == "articles":
        lids = _kept_lids(store, node["_id"], filters, _leden(node), wait_for_lids)
    capacities = (
        _capacity_counts(store, node["_id"])
        if collection == COLLECTION_MEMBERS and filters.status is None
        else {}
    )
    end = offset + limit
    buckets = [
        NeighborBucket(
            facet=facet,
            next_offset=end if end < facet.count else None,
            entries=pages.get((facet.relation, facet.direction, facet.collection), []),
            lid_counts=(lids or {}).get(
                (facet.relation, facet.direction, facet.collection)
            ),
            capacity_counts=(
                capacities.get(facet.collection)
                if (facet.relation, facet.direction) == (RELATION_AUTHORED, "outbound")
                else None
            ),
        )
        for facet in facets
    ]
    return NodeGraphData(node=node, buckets=buckets, lid_counts_pending=lids is None)


def _count_facets(
    store: GraphStore, node_id: str, filters: NeighborFilter
) -> list[NeighborFacet]:
    """Count the edges of a node per (relation, direction, neighbour collection).

    One pass over the edges of the node, with no document read: a faction has a million
    ``VOTED`` edges. A collection holds one node type, so the neighbours are never read.
    """
    parts = []
    for direction in filters.directions:
        own, _, other_collection = _EDGE_SIDES[direction]
        collections = (
            f"AND e.{other_collection} = ANY(%(collections)s)"
            if filters.collections is not None
            else ""
        )
        parts.append(
            f"""
            SELECT e.relation, '{direction}' AS direction, e.{other_collection} AS collection,
                   count(*)::int AS count
            FROM edges e
            WHERE e.{own} = %(node_id)s {filters.edge_sql("e")} {collections}
            GROUP BY e.relation, e.{other_collection}
            """
        )
    statement = (
        " UNION ALL ".join(parts)
        + " ORDER BY relation NULLS FIRST, direction, collection NULLS FIRST"
    )
    params = {
        "node_id": node_id,
        "collections": filters.collections,
        **filters.edge_params(),
    }
    return [
        NeighborFacet(
            relation=row["relation"],
            direction=row["direction"],
            collection=row["collection"],
            count=row["count"],
        )
        for row in store.query(statement, params)
    ]


# The lids an edge cites, from its ``meta``: ``lid``, ``leden``, and the ``leden`` of each
# of its ``mentions`` (a judgment cites an article in several places).
_LIDS = """ARRAY(
    SELECT DISTINCT lid FROM (
        SELECT e.doc -> 'meta' ->> 'lid'
        UNION ALL
        SELECT unnest(lg_text_array(e.doc -> 'meta' -> 'leden'))
        UNION ALL
        SELECT unnest(lg_text_array(m.mention -> 'leden'))
        FROM json_array_elements(
            CASE WHEN json_typeof(e.doc -> 'meta' -> 'mentions') = 'array'
                 THEN e.doc -> 'meta' -> 'mentions' END
        ) AS m(mention)
    ) AS l(lid)
    WHERE lid IS NOT NULL AND lid <> ''
)"""


def _leden(article: dict[str, Any]) -> list[str] | None:
    """The numbers of the leden of *article* (``parts`` of kind ``lid``), in lower case;
    None for an article without ``parts`` (a stub: what it has is not known)."""
    parts = (article.get("props") or {}).get("parts")
    if not isinstance(parts, list):
        return None
    return [
        str(part["number"]).lower()
        for part in parts
        if isinstance(part, dict) and part.get("kind") == "lid" and part.get("number")
    ]


def _kept_lids(
    store: GraphStore,
    node_id: str,
    filters: NeighborFilter,
    leden: list[str] | None,
    wait: bool = True,
) -> dict[tuple[str | None, str, str], dict[str, int]] | None:
    """``_count_lids``, kept ``LIDS_MAX_AGE`` whatever the data does: it reads the ``meta``
    of every edge of the article (of 6:162 BW, 9,000: half a second warm, seconds cold),
    and every poll writes edges, so kept per version of them it was read again cold after
    each (6–9 s on prod, 2026-10-09); a poll moves the counts of a much cited article by a
    handful. Without *wait* (a light node, ``limit=1``) an earlier count at once, and a
    new one waited for ``LIGHT_LIDS_WAIT`` at most: None past it, the count going on in the
    background (7.0 s for the light node of 6:162 BW after a deploy, 10 Oct)."""
    leden_key = None if leden is None else tuple(leden)

    def kept() -> dict[tuple[str | None, str, str], dict[str, int]]:
        return lasting(
            store,
            ("lid-counts", node_id, filters, leden_key),
            lambda: _count_lids(store, node_id, filters, leden),
            LIDS_MAX_AGE,
        )

    if wait:
        return kept()
    left = read_time_left()
    token = set_read_deadline(
        LIGHT_LIDS_WAIT if left is None else min(LIGHT_LIDS_WAIT, left)
    )
    try:
        with stale_wait(0.0):
            return kept()
    except ReadTimedOut:
        return None
    finally:
        reset_read_deadline(token)


# How long the lid counts of an article are kept (seconds); a newer count is made in the
# background after that, while the kept one is served.
LIDS_MAX_AGE = 3600.0
# How long a light node waits for lid counts not kept yet (seconds): those of an article
# with few citations come in time, those of a much cited one are counted on.
LIGHT_LIDS_WAIT = 0.5


def _count_lids(
    store: GraphStore,
    node_id: str,
    filters: NeighborFilter,
    leden: list[str] | None,
) -> dict[tuple[str | None, str, str], dict[str, int]]:
    """Per bucket of an article, how many of its edges cite each lid ("" those that cite
    none; an edge that cites two counts for each): of the whole bucket, not its page. Only
    the *leden* the article has count (a citation can give it the lid of another article
    it names); every lid of an article whose leden are not known. Reads the ``meta`` of
    every edge of the article (hundreds; not of a faction's million); a bucket of which no
    edge cites a lid is left out."""
    parts = []
    for direction in filters.directions:
        own, _, other_collection = _EDGE_SIDES[direction]
        collections = (
            f"AND e.{other_collection} = ANY(%(collections)s)"
            if filters.collections is not None
            else ""
        )
        parts.append(
            f"""
            SELECT e.relation, '{direction}' AS direction,
                   e.{other_collection} AS collection, {_LIDS} AS lids
            FROM edges e
            WHERE e.{own} = %(node_id)s {filters.edge_sql("e")} {collections}
            """
        )
    statement = f"""
        SELECT c.relation, c.direction, c.collection, lid, count(*)::int AS count
        FROM (
            SELECT c.relation, c.direction, c.collection, ARRAY(
                SELECT l FROM unnest(c.lids) AS l
                WHERE %(leden)s::text[] IS NULL OR lower(l) = ANY(%(leden)s::text[])
            ) AS lids
            FROM ({" UNION ALL ".join(parts)}) c
        ) c
        CROSS JOIN LATERAL unnest(
            CASE WHEN cardinality(c.lids) > 0 THEN c.lids ELSE ARRAY[''] END
        ) AS lid
        GROUP BY c.relation, c.direction, c.collection, lid
        ORDER BY c.relation NULLS FIRST, c.direction NULLS FIRST,
                 c.collection NULLS FIRST, lid NULLS FIRST
        """
    params = {
        "node_id": node_id,
        "collections": filters.collections,
        "leden": leden,
        **filters.edge_params(),
    }
    found: dict[tuple[str | None, str, str], dict[str, int]] = {}
    for row in store.query(statement, params):
        bucket = (row["relation"], row["direction"], row["collection"])
        found.setdefault(bucket, {})[row["lid"]] = row["count"]
    return {bucket: lids for bucket, lids in found.items() if set(lids) != {""}}


def _read_pages(
    store: GraphStore,
    node_id: str,
    filters: NeighborFilter,
    facets: Iterable[NeighborFacet],
    limit: int,
    offset: int,
    canvas: bool = False,
) -> dict[tuple[str | None, str, str], list[NeighborEntry]]:
    """Read ``limit`` neighbours from ``offset`` on in every facet that reaches that far;
    with *canvas* only what the canvas of the explorer reads of them.

    One query per request: each facet reads its own page of edges in key order, so that a
    page is the same on every request. ``limit`` and ``offset`` count edges, so an edge
    whose neighbour is gone leaves its page one short.
    """
    wanted: dict[Direction, list[NeighborFacet]] = {}
    for facet in facets:
        if facet.count > offset:
            wanted.setdefault(facet.direction, []).append(facet)
    if not wanted:
        return {}
    status = "AND k.status = %(status)s" if filters.status is not None else ""
    params: dict[str, Any] = {
        "node_id": node_id,
        "offset": offset,
        "limit": limit,
        **filters.edge_params(),
    }
    props = canvas_props("n") if canvas else light_props("n")
    edge_doc = canvas_edge_doc if canvas else light_edge_doc
    parts = []
    for direction, buckets in wanted.items():
        own, other, other_collection = _EDGE_SIDES[direction]
        # a relation is matched as equal, so that the index gives the edges of a bucket in
        # key order and a page stops after its limit; the rare bucket without a relation
        # apart. The page's keys come from the index alone (``edges_to_cover``,
        # ``edges_from_cover``), its edges by their key after: read whole, a hub's every
        # edge was read and sorted for a page of them (the planner takes a bucket for one
        # edge)
        # and per collection of the neighbours, named in the statement: the view ``nodes``
        # then reads that table alone (a value from the bucket left every table of it to be
        # probed for every neighbour, 17 index probes for one)
        for name, collection, matched in (
            (name, collection, [b for b in named if b.collection == collection])
            for name, named in (
                ("named", [b for b in buckets if b.relation is not None]),
                ("unnamed", [b for b in buckets if b.relation is None]),
            )
            for collection in dict.fromkeys(b.collection for b in named)
        ):
            if collection not in _ALLOWED_NODE_COLLECTIONS:
                continue  # an edge to a table the graph does not have: no neighbour
            group = f"{direction}_{name}_{collection}"
            params[f"{group}_relations"] = [b.relation for b in matched]
            params[f"{group}_collections"] = [b.collection for b in matched]
            relation = (
                "k.relation = b.relation" if name == "named" else "k.relation IS NULL"
            )
            parts.append(
                f"""
                SELECT b.relation, '{direction}' AS direction, b.collection, b.ord,
                       e.key AS edge_key, e.from_id, e.to_id, e.doc,
                       n.id, n.key, n.type, n.labels, {props} AS props
                FROM unnest(%({group}_relations)s::text[],
                            %({group}_collections)s::text[])
                    WITH ORDINALITY AS b(relation, collection, ord)
                CROSS JOIN LATERAL (
                    SELECT e.* FROM (
                        SELECT k.key FROM edges k
                        WHERE k.{own} = %(node_id)s
                          AND {relation}
                          AND k.{other_collection} = b.collection {status}
                        ORDER BY k.key
                        LIMIT %(limit)s OFFSET %(offset)s
                    ) page
                    JOIN edges e ON e.key = page.key
                ) e
                JOIN nodes n ON n.id = e.{other} AND n.collection = '{collection}'
                """
            )
    statement = " UNION ALL ".join(parts) + " ORDER BY direction, ord, edge_key"
    pages: dict[tuple[str | None, str, str], list[NeighborEntry]] = {}
    # a page of each bucket in key order, never a hub's bucket read whole and sorted
    for row in store.query(statement, params, index_order=True):
        entry = NeighborEntry(
            doc=light_node_doc(row),
            edge=edge_doc({**row, "key": row["edge_key"]}),
            direction=row["direction"],
        )
        pages.setdefault(
            (row["relation"], row["direction"], row["collection"]), []
        ).append(entry)
    return pages


# How many neighbours ``lg_walk`` looks up at a time: a capped walk stops looking them up
# once the cap is reached.
_NEIGHBOUR_CHUNK = 500


def _walk_params(
    focal_id: str, depth: int, cap: int, filters: NeighborFilter
) -> dict[str, Any]:
    """The arguments of ``lg_walk`` (``db/schema.py``) for a walk from *focal_id*."""
    return {
        "focal": focal_id,
        "depth": depth,
        "cap": cap,
        "relations": list(filters.relations) if filters.relations is not None else None,
        "status": filters.status,
        "outbound": "outbound" in filters.directions,
        "inbound": "inbound" in filters.directions,
        "collections": filters.collections,
        "tables": sorted(_ALLOWED_NODE_COLLECTIONS),
        "chunk": _NEIGHBOUR_CHUNK,
        **filters.edge_params(),
    }


def get_node_neighborhood(
    store: GraphStore,
    collection: str,
    key: str,
    *,
    depth: int = 3,
    cap: int = 200,
    filters: NeighborFilter = NO_FILTER,
    canvas: bool = False,
) -> dict[str, Any]:
    """Every node and edge within ``depth`` hops of a node, breadth first.

    ``cap`` bounds the number of nodes so a hub cannot flood the response. ``filters``
    shape the walk itself: it follows only edges of the given relations and status, in the
    given direction, and goes through nodes of the given types (the focal node is always
    kept). The result also carries every other edge of those relations and that status
    between two of the nodes kept, so the frontend can render the full subgraph. With
    *canvas* a node carries only the props the canvas of the explorer draws
    (``_rows.CANVAS_PROPS``), as a neighbour of ``props=canvas`` does.
    """
    focal = _load_node(store, collection, key)
    props = canvas_props("n") if canvas else light_props("n")
    depth = max(1, min(depth, 4))
    cap = max(1, min(cap, 1000))
    # One statement: the walk in the database (breadth first, D9: a level is kept in id
    # order until the cap; a node of a type the filter leaves out is seen but neither kept
    # nor walked through), the nodes it kept, and the edges between them and the focal
    # node.
    found = next(
        store.query(
            f"""
            WITH walked AS (
                SELECT lg_walk(%(focal)s, %(depth)s, %(cap)s, %(relations)s, %(status)s,
                               %(outbound)s, %(inbound)s, %(collections)s, %(tables)s,
                               %(chunk)s) AS ids
            )
            SELECT
                (SELECT coalesce(json_agg(json_build_array(
                     n.id, n.key, n.type, n.labels, {props}) ORDER BY n.id), '[]')
                 FROM walked w, nodes n
                 WHERE n.id = ANY(w.ids)
                   -- only the tables of the collections walked to are asked
                   AND n.collection = ANY(ARRAY(
                       SELECT DISTINCT split_part(x, '/', 1) FROM unnest(w.ids) x))
                ) AS nodes,
                (SELECT coalesce(json_agg(json_build_array(
                     e.key, e.from_id, e.to_id, e.doc) ORDER BY e.key), '[]')
                 FROM walked w, edges e
                 WHERE e.from_id = ANY(w.ids || %(focal)s::text)
                   AND e.to_id = ANY(w.ids || %(focal)s::text) {filters.edge_sql("e")})
                    AS edges
            FROM walked
            """,
            _walk_params(focal["_id"], depth, cap, filters),
        )
    )
    nodes = [dict(zip(_NODE_FIELDS, row, strict=True)) for row in found["nodes"]]
    edges = [dict(zip(_EDGE_FIELDS, row, strict=True)) for row in found["edges"]]
    return {
        "focal": focal,
        "nodes": [light_node_doc(row) for row in nodes],
        "edges": [light_edge_doc(row) for row in edges],
        "buckets": _buckets(store, focal["_id"], filters, {row["id"] for row in nodes}),
    }


# Per collection, the neighbours of a node along the edges a walk follows (``lg_walk``'s
# first level): from the edges alone, through their covering indexes (a neighbour that is
# gone counts too).
_BUCKETS = """
SELECT split_part(x.id, '/', 1) AS collection, count(*)::int AS total,
       coalesce(array_agg(x.id ORDER BY x.id ASC NULLS LAST), '{}') AS ids
FROM (
    SELECT e.to_id AS id FROM edges e
    WHERE %(outbound)s AND e.from_id = %(focal)s
      AND (%(relations)s::text[] IS NULL OR e.relation = ANY(%(relations)s::text[]))
      AND (%(status)s::text IS NULL OR e.status = %(status)s::text)
    UNION
    SELECT e.from_id FROM edges e
    WHERE %(inbound)s AND e.to_id = %(focal)s
      AND (%(relations)s::text[] IS NULL OR e.relation = ANY(%(relations)s::text[]))
      AND (%(status)s::text IS NULL OR e.status = %(status)s::text)
) x
WHERE x.id <> %(focal)s
GROUP BY 1
ORDER BY 1 ASC NULLS LAST
"""


def _buckets(
    store: GraphStore, focal_id: str, filters: NeighborFilter, kept: set[str]
) -> list[dict[str, Any]]:
    """Per collection of the node's own neighbours (the first level of its neighbourhood),
    by name: ``total``, its neighbours there along the edges walked, of the types asked for,
    and ``kept``, those the walk kept under its cap."""
    found = []
    for row in store.query(_BUCKETS, _walk_params(focal_id, 1, 1, filters)):
        collection = row["collection"]
        if collection not in _ALLOWED_NODE_COLLECTIONS or (
            filters.collections is not None and collection not in filters.collections
        ):
            continue
        found.append(
            {
                "collection": collection,
                "total": row["total"],
                "kept": sum(1 for node_id in row["ids"] if node_id in kept),
            }
        )
    return found
