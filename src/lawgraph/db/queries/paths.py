"""The shortest paths between chosen nodes (``GET /api/paths``): for every pair, one path of
at most ``max_depth`` edges, followed in either direction.

A breadth-first search from both ends of a pair, one level at a time, the smaller side
first: each level is one read of the edges at the nodes of the side, by ``from_id`` and by
``to_id`` (``edges_from``, ``edges_to``). The neighbours of a level are taken in id order and
kept until ``LEVEL_CAP``, as the neighbourhood keeps a level (D9); a level cut there makes the
answer ``capped``. Of the paths of the same length the one through the lowest ids is
kept, so an answer does not change from one call to the next. No edge is derived: a path is
edges of the graph.

A path does not pass through a law by its articles: the ``PART_OF`` edge of an article and
its law is followed only where the law is one end of the pair (``through_laws`` allows it).
Else every two articles of a law, or a paper that cites a law and any article of it, are
two steps apart, and that path says nothing. ``relations`` keeps the edges of those
relations alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

from lawgraph.config.constants import COLLECTION_INSTRUMENTS, RELATION_PART_OF
from lawgraph.db import GraphStore
from lawgraph.db._rows import edge_doc, light_props, node_doc

LEVEL_CAP = 5000  # the nodes a side keeps of one level
_ROWS_PER_LEVEL = LEVEL_CAP * 20  # the edges read for one level, at most

# The edges a path may follow: of ``relations`` (all when null), and the ``PART_OF`` of a
# law only where the law is an end of the pair, unless ``through_laws``.
_FOLLOWED = f"""
  AND (%(relations)s::text[] IS NULL OR e.relation = ANY(%(relations)s))
  AND (%(through_laws)s OR e.relation <> '{RELATION_PART_OF}'
       OR NOT (e.from_collection = '{COLLECTION_INSTRUMENTS}' AND e.from_id <> ALL(%(ends)s))
          AND NOT (e.to_collection = '{COLLECTION_INSTRUMENTS}' AND e.to_id <> ALL(%(ends)s)))
"""

# ``law``: the law a ``PART_OF`` edge reaches (null for any other edge), which a pair may
# not pass through unless it is one of its ends (``_through_law``).
_LAW = f"""CASE WHEN e.relation = '{RELATION_PART_OF}' THEN
    CASE WHEN e.from_collection = '{COLLECTION_INSTRUMENTS}' THEN e.from_id
         WHEN e.to_collection = '{COLLECTION_INSTRUMENTS}' THEN e.to_id END
END"""

_NEIGHBOURS_SQL = f"""
SELECT e.from_id AS node, e.to_id AS neighbour, e.key, {_LAW} AS law
FROM edges e WHERE e.from_id = ANY(%(frontier)s) {_FOLLOWED}
UNION ALL
SELECT e.to_id, e.from_id, e.key, {_LAW}
FROM edges e WHERE e.to_id = ANY(%(frontier)s) {_FOLLOWED}
ORDER BY 2, 3
LIMIT %(limit)s
"""

_NODES_SQL = f"""
SELECT n.id, n.key, n.type, n.labels, {light_props("n")} AS props
FROM nodes n
WHERE n.id = ANY(%(ids)s)
  AND n.collection = ANY(ARRAY(SELECT DISTINCT split_part(x, '/', 1) FROM unnest(%(ids)s) x))
ORDER BY n.id
"""

_EDGES_SQL = """
SELECT e.key, e.from_id, e.to_id, e.doc FROM edges e WHERE e.key = ANY(%(keys)s) ORDER BY e.key
"""


@dataclass
class _Side:
    """One end of a search: every node it reached, with its depth and how (the node before
    it and the edge between them)."""

    start: str
    reached: dict[str, tuple[int, str | None, str | None]] = field(default_factory=dict)
    frontier: list[str] = field(default_factory=list)
    depth: int = 0

    def __post_init__(self) -> None:
        self.reached[self.start] = (0, None, None)
        self.frontier = [self.start]

    def steps_to(self, node: str) -> tuple[list[str], list[str]]:
        """The nodes from the start to *node* and the edges between them."""
        nodes, edges = [node], []
        _, before, edge = self.reached[node]
        while before is not None and edge is not None:
            nodes.append(before)
            edges.append(edge)
            _, before, edge = self.reached[before]
        return nodes[::-1], edges[::-1]


@dataclass(frozen=True)
class Followed:
    """Which edges a path may follow (``get_paths``)."""

    relations: list[str] | None = None
    through_laws: bool = False


EVERY_EDGE_BUT_THROUGH_LAWS = Followed()


@dataclass(frozen=True)
class Path:
    """One path: its nodes from *source* to *target* and the edges between them."""

    source: str
    target: str
    nodes: tuple[str, ...]
    edges: tuple[str, ...]


class _Levels:
    """The edges at a frontier, read once for every pair of a request: an id is an end of
    several pairs, and its side reads the same levels in each. Read with every id of the
    request as an end; a law a pair may not pass through is left out per pair
    (``_expand``)."""

    def __init__(self, store: GraphStore, followed: Followed, ids: list[str]) -> None:
        self.store = store
        self.followed = followed
        self.ids = ids
        self.read: dict[tuple[str, ...], list[dict[str, Any]]] = {}

    def at(self, frontier: list[str]) -> list[dict[str, Any]]:
        key = tuple(frontier)
        if key not in self.read:
            self.read[key] = list(
                self.store.query(
                    _NEIGHBOURS_SQL,
                    {
                        "frontier": frontier,
                        "limit": _ROWS_PER_LEVEL,
                        "relations": self.followed.relations,
                        "through_laws": self.followed.through_laws,
                        "ends": self.ids,
                    },
                )
            )
        return self.read[key]


def _expand(levels: _Levels, side: _Side, ends: list[str]) -> bool:
    """Read the next level of *side* (a path between *ends*); whether it was cut at
    ``LEVEL_CAP``."""
    rows = [
        row
        for row in levels.at(side.frontier)
        if levels.followed.through_laws or row["law"] is None or row["law"] in ends
    ]
    side.depth += 1
    level: list[str] = []
    capped = False
    for row in rows:
        neighbour = row["neighbour"]
        if neighbour in side.reached:
            continue
        if len(level) == LEVEL_CAP:
            capped = True
            break
        side.reached[neighbour] = (side.depth, row["node"], row["key"])
        level.append(neighbour)
    side.frontier = level
    return capped


def _shortest(
    levels: _Levels, source: str, target: str, max_depth: int
) -> tuple[Path | None, bool]:
    """The shortest path from *source* to *target* within *max_depth* edges, or None; and
    whether a level was cut on the way."""
    ends = _Side(source), _Side(target)
    capped = False
    while ends[0].depth + ends[1].depth < max_depth:
        side, other = sorted(ends, key=lambda s: (len(s.frontier), s is ends[1]))
        if not side.frontier:
            break
        capped |= _expand(levels, side, [source, target])
        met = [n for n in side.frontier if n in other.reached]
        if met:
            # the nearest to the other end, then the lowest id
            node = min(met, key=lambda n: (other.reached[n][0], n))
            first, second = (side, other) if side is ends[0] else (other, side)
            to_node, edges_to = first.steps_to(node)
            from_node, edges_from = second.steps_to(node)
            nodes = (*to_node, *from_node[::-1][1:])
            return Path(source, target, nodes, (*edges_to, *edges_from[::-1])), capped
    return None, capped


def get_paths(
    store: GraphStore,
    ids: list[str],
    max_depth: int,
    followed: Followed = EVERY_EDGE_BUT_THROUGH_LAWS,
) -> dict[str, Any]:
    """For every pair of *ids*, the shortest path between them within *max_depth* edges
    along the edges *followed* lets through: ``{paths, nodes, edges, capped}``. ``paths`` holds a path for each pair that has one,
    in the order of *ids*; ``nodes`` and ``edges`` every node and edge on them, each once.
    A path through a node that is not there (an edge to a missing node) is left out."""
    found: list[Path] = []
    capped = False
    chosen = list(dict.fromkeys(ids))
    levels = _Levels(store, followed, chosen)
    for source, target in combinations(chosen, 2):
        path, cut = _shortest(levels, source, target, max_depth)
        capped |= cut
        if path is not None:
            found.append(path)
    node_ids = sorted({n for p in found for n in p.nodes})
    nodes = (
        {row["id"]: node_doc(row) for row in store.query(_NODES_SQL, {"ids": node_ids})}
        if node_ids
        else {}
    )
    found = [p for p in found if all(n in nodes for n in p.nodes)]
    edge_keys = sorted({e for p in found for e in p.edges})
    edges = (
        [edge_doc(row) for row in store.query(_EDGES_SQL, {"keys": edge_keys})]
        if edge_keys
        else []
    )
    return {
        "paths": found,
        "nodes": [nodes[n] for n in sorted({n for p in found for n in p.nodes})],
        "edges": edges,
        "capped": capped,
    }
