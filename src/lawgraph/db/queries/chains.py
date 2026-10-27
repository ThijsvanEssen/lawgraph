"""The chains between two chosen nodes (``GET /api/chains``): rows of 1 to ``MAX_STEPS`` steps
from one to the other, searched on the steps between the sources (``source_steps``, built by
``semantic graph-steps``: ``queries/source_steps.py``).

A *step* joins two sources (laws and articles, ``STEP_COLLECTIONS``): by an edge between them,
or by a node with an edge to both and to at most ``THROUGH_CAP`` sources (a paper that names
both, a judgment that cites both); its ``weight`` says how strong it is. An end that is no
source (a judgment, a paper) has its steps read from its edges by the same rules, counted
among the sources of what it shares. The ``PART_OF`` of a law that is an end and its articles
is a step too; any other ``PART_OF`` of a law is none, so that two articles of one law are not
one step apart.

A *chain* is a row of steps from one end to the other through sources; each node is once in
it. The shortest chains first: a source that a shorter chain passes, or that the ends share,
starts no longer chain. In a length the strongest first: the highest weight of its weakest
step, then the weight of its steps together, then the ids of its sources. The chains shown
pass each source between the ends once: a chain through a source an earlier one passes is
counted, not shown.

Up to ``EXACT_STEPS`` steps every chain is counted: the steps of each end, and for three the
steps between those (one read of the table, of at most ``LEVEL_CAP`` sources of an end).
Longer chains are searched best first from both ends, a level at a time: of each level the
``FRONTIER_CAP`` strongest go on, each with its ``TOP_STEPS`` strongest steps, and each source
keeps the strongest way to it; a chain is a source where both meet. Their ``total`` is then a
lower bound, and the block not ``complete``, when the search left a way out.

Of each step shown its way: the edge between its sources, else of the nodes they share (as
the table counts them, none of the chain) the one with the fewest sources, then the lowest id;
read for the steps shown alone, in one read of the edges of their sources. No edge is derived.
"""

from __future__ import annotations

import heapq
import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from itertools import product
from typing import Any

from lawgraph.config.constants import COLLECTION_INSTRUMENTS, RELATION_PART_OF
from lawgraph.db import GraphStore
from lawgraph.db._rows import light_edge_doc
from lawgraph.db.queries.nodes import light_nodes
from lawgraph.db.queries.paths import EDGES_SQL, FOLLOWED
from lawgraph.db.queries.source_steps import (
    DIRECT_WEIGHT,
    KEPT,
    STEP_COLLECTIONS,
    THROUGH_CAP,
)
from lawgraph.db.schema import SOURCE_STEP_NODES_TABLE, SOURCE_STEPS_TABLE
from lawgraph.db.store import read_budget

MAX_STEPS = 6
EXACT_STEPS = 3  # the longest chains counted whole
# The sources of an end a chain of three steps starts from (the strongest), the
# neighbours of an end that is no source its steps are read from, the sources of a level
# a longer search goes on from (the strongest) and the steps of each it takes.
LEVEL_CAP = 5000
AROUND_CAP = 1000
FRONTIER_CAP = 200
TOP_STEPS = 50
# The edges of a node an end that is no source shares, read each way: at it the node
# touches more than ``THROUGH_CAP`` sources.
_PER_WAY = 4 * THROUGH_CAP
# The ways of a step tried for a chain whose nodes must differ: more than the other nodes
# of the longest chain, so that one of them is always free.
_OPTIONS = 2 * MAX_STEPS + 1
# How long the search may read (seconds): past it, the chains found by then (``partial``);
# what is left of the deadline of the request reads their ways, nodes and edges.
CHAINS_BUDGET = 10.0
CHAINS_RESERVE = 3.0

_SOURCES = ", ".join(f"'{c}'" for c in STEP_COLLECTIONS)

# The steps of each source of ``ids``, both ways of the table.
_STEPS_SQL = f"""
SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM {SOURCE_STEPS_TABLE} s WHERE s.a = ANY(%(ids)s::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM {SOURCE_STEPS_TABLE} s WHERE s.b = ANY(%(ids)s::text[])
"""

# Of each source of ``ids`` its ``top`` strongest steps.
_TOP_STEPS_SQL = f"""
SELECT f.id AS node, t.other, t.weight, t.ways, t.direct
FROM unnest(%(ids)s::text[]) AS f(id)
CROSS JOIN LATERAL (
    SELECT u.other, u.weight, u.ways, u.direct FROM (
        (SELECT s.b AS other, s.weight, s.ways, s.direct FROM {SOURCE_STEPS_TABLE} s
         WHERE s.a = f.id ORDER BY s.weight DESC LIMIT %(top)s)
        UNION ALL
        (SELECT s.a, s.weight, s.ways, s.direct FROM {SOURCE_STEPS_TABLE} s
         WHERE s.b = f.id ORDER BY s.weight DESC LIMIT %(top)s)
    ) u
    ORDER BY u.weight DESC, u.other
    LIMIT %(top)s
) t
"""

# The steps between a source of ``near`` and one of ``far``.
_BETWEEN_SQL = f"""
SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM {SOURCE_STEPS_TABLE} s WHERE s.a = ANY(%(near)s::text[]) AND s.b = ANY(%(far)s::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM {SOURCE_STEPS_TABLE} s WHERE s.b = ANY(%(near)s::text[]) AND s.a = ANY(%(far)s::text[])
"""

# The articles of a law that is an end (its ``PART_OF``).
_PARTS_SQL = f"""
SELECT e.from_id AS part FROM edges e
WHERE e.to_id = %(law)s AND e.relation = '{RELATION_PART_OF}'
  AND e.from_collection IN ({_SOURCES})
"""

# Of an end that is no source: its neighbours (at most ``cap``), and of each the sources and
# ends it has an edge to (at most ``per`` each way).
_AROUND_END_SQL = f"""
WITH near AS MATERIALIZED (
    SELECT DISTINCT n.x FROM (
        (SELECT e.to_id AS x FROM edges e WHERE e.from_id = %(end)s {FOLLOWED})
        UNION ALL
        (SELECT e.from_id FROM edges e WHERE e.to_id = %(end)s {FOLLOWED})
    ) n
    WHERE n.x <> %(end)s
    LIMIT %(cap)s
)
SELECT n.x, t.other, t.outbound FROM near n
LEFT JOIN LATERAL (
    (SELECT e.to_id AS other, true AS outbound FROM edges e
     WHERE e.from_id = n.x AND (e.to_collection IN ({_SOURCES}) OR e.to_id = ANY(%(ends)s))
       AND {KEPT}
     LIMIT %(per)s)
    UNION ALL
    (SELECT e.from_id, false FROM edges e
     WHERE e.to_id = n.x AND (e.from_collection IN ({_SOURCES}) OR e.from_id = ANY(%(ends)s))
       AND {KEPT}
     LIMIT %(per)s)
) t ON true
"""

# The edge between the two sources of a step: as ``KEPT``, and the ``PART_OF`` of a law
# that is an end.
_FOLLOWED_WAY = f"""e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM '{RELATION_PART_OF}'
         OR (e.from_collection <> '{COLLECTION_INSTRUMENTS}' OR e.from_id = ANY(%(ends)s))
            AND (e.to_collection <> '{COLLECTION_INSTRUMENTS}' OR e.to_id = ANY(%(ends)s)))"""

# Per step (``first`` to ``second``, its number ``i``) the edge between them (``x`` null) and
# every node both have an edge to, with those edges and the sources of the node (1 where
# ``source_step_nodes`` does not hold it): the edges of each source read once.
_WAYS_SQL = f"""
WITH pair AS (
    SELECT p.first, p.second, p.i
    FROM unnest(%(firsts)s::text[], %(seconds)s::text[]) WITH ORDINALITY AS p(first, second, i)
), node AS (
    SELECT DISTINCT n.id
    FROM pair CROSS JOIN LATERAL unnest(ARRAY[pair.first, pair.second]) AS n(id)
), at AS MATERIALIZED (
    SELECT n.id, r.x, r.key, r.kept, r.followed FROM node n
    CROSS JOIN LATERAL (
        (SELECT e.to_id AS x, e.key, {KEPT} AS kept, {_FOLLOWED_WAY} AS followed
         FROM edges e WHERE e.from_id = n.id)
        UNION ALL
        (SELECT e.from_id, e.key, {KEPT}, {_FOLLOWED_WAY}
         FROM edges e WHERE e.to_id = n.id)
    ) r
)
SELECT p.i, f.x, min(f.key) AS from_first, min(s.key) AS to_second,
       coalesce(w.sources, 1) AS sources
FROM pair p
JOIN at f ON f.id = p.first AND f.kept
JOIN at s ON s.id = p.second AND s.x = f.x AND s.kept
LEFT JOIN {SOURCE_STEP_NODES_TABLE} w ON w.id = f.x
GROUP BY p.i, f.x, w.sources
UNION ALL
SELECT p.i, NULL, min(f.key), NULL, 0
FROM pair p JOIN at f ON f.id = p.first AND f.x = p.second AND f.followed
GROUP BY p.i
"""


@dataclass(frozen=True)
class Link:
    """A step as the table holds it: its weight, the nodes its sources share, and whether
    an edge joins them."""

    weight: float
    ways: int
    direct: bool


# Per source the step to it.
Links = dict[str, Link]


@dataclass(frozen=True)
class Step:
    """One step of a chain: from *source* to *target* by the edge between them (``via``
    None) or through the node they share, its edges in that order; ``ways`` the edge and
    the nodes they share, ``weight`` how strong it is."""

    source: str
    target: str
    via: str | None
    edges: tuple[str, ...]
    ways: int
    weight: float


@dataclass(frozen=True)
class Chain:
    """The sources of a chain from one end to the other, its steps, and its weight: that of
    its weakest step."""

    sources: tuple[str, ...]
    steps: tuple[Step, ...]
    weight: float


@dataclass
class Block:
    """The chains of one length: *total* of them, the first in ``chains``; ``complete``
    when the search left none out."""

    steps: int
    total: int = 0
    chains: list[Chain] = field(default_factory=list)
    complete: bool = False


@dataclass
class Chains:
    blocks: list[Block]
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    capped: bool
    partial: bool


@dataclass(frozen=True)
class Found:
    """A chain found: the sources between the ends and its steps."""

    between: tuple[str, ...]
    links: tuple[Link, ...]

    def rank(self) -> tuple[float, float, tuple[str, ...]]:
        """The strongest first: the weakest step, the steps together, the ids."""
        weights = [link.weight for link in self.links]
        return -min(weights), -sum(weights), self.between


@dataclass(frozen=True)
class Label:
    """The strongest way from an end to a source of a level: the sources from the end and
    the steps to them."""

    path: tuple[str, ...]
    links: tuple[Link, ...]

    @property
    def strength(self) -> tuple[float, float]:
        weights = [link.weight for link in self.links]
        return min(weights), sum(weights)

    def on(self, node: str, link: Link) -> Label:
        return Label((*self.path, node), (*self.links, link))


def is_source(node: str) -> bool:
    return node.split("/", 1)[0] in STEP_COLLECTIONS


def add_link(links: Links, node: str, link: Link) -> None:
    """*link* to *node*, together with the one there: a way more."""
    old = links.get(node)
    if old is not None:
        link = Link(
            old.weight + link.weight, old.ways + link.ways, old.direct or link.direct
        )
    links[node] = link


def _links(rows: Iterable[dict[str, Any]]) -> dict[str, Links]:
    found: dict[str, Links] = defaultdict(dict)
    for row in rows:
        found[row["node"]][row["other"]] = Link(
            float(row["weight"]), int(row["ways"]), bool(row["direct"])
        )
    return found


def strongest(links: Links, cap: int) -> list[str]:
    """The *cap* sources of *links* with the strongest step, then by id."""
    return sorted(links, key=lambda node: (-links[node].weight, node))[:cap]


def meet(from_a: dict[str, Label], from_b: dict[str, Label]) -> tuple[list[Found], int]:
    """The chains where the levels from both ends meet, by the source they meet at; and
    how many met twice at a source (a chain left out)."""
    found, twice = [], 0
    for node in sorted(from_a.keys() & from_b.keys()):
        there, back = from_a[node], from_b[node]
        between = (*there.path, *back.path[-2::-1])
        if len(set(between)) == len(between):
            found.append(Found(between, (*there.links, *back.links[::-1])))
        else:
            twice += 1
    return found, twice


class _Search:
    """The chains of two ends, found per length."""

    def __init__(self, store: GraphStore, ends: tuple[str, str]) -> None:
        self.store = store
        self.ends = ends
        self.top: dict[str, Links] = {}
        # the first length the search left a way out of
        self.cut_at: int | None = None
        self.found: list[list[Found]] = []

    def _cut(self, length: int) -> None:
        self.cut_at = length if self.cut_at is None else min(self.cut_at, length)

    # ── reads ────────────────────────────────────────────────────────────────

    def steps_of(self, end: str) -> Links:
        """The steps of an end: from the table for a source (and the articles of a law),
        else from its edges."""
        if not is_source(end):
            return self._steps_around(end)
        links = dict(_links(self.store.query(_STEPS_SQL, {"ids": [end]})).get(end, {}))
        if end.startswith(f"{COLLECTION_INSTRUMENTS}/"):
            for part in self.store.query(_PARTS_SQL, {"law": end}):
                if not (part in links and links[part].direct):
                    add_link(links, part, Link(DIRECT_WEIGHT, 0, True))
        return links

    def _steps_around(self, end: str) -> Links:
        """The steps of an end that is no source, by the rules of the table: the end is
        one of the sources of each node it shares."""
        rows = list(
            self.store.query(
                _AROUND_END_SQL,
                {
                    "end": end,
                    "ends": list(self.ends),
                    "cap": AROUND_CAP,
                    "per": _PER_WAY,
                    "relations": None,
                    "through_laws": False,
                },
            )
        )
        touched: dict[str, set[str]] = defaultdict(set)
        for row in rows:
            touched[row["x"]].update(
                {end} if row["other"] is None else {end, row["other"]}
            )
        if len(touched) == AROUND_CAP:
            self._cut(1)
        each_way = Counter((row["x"], row["outbound"]) for row in rows)
        over = {x for (x, _), n in each_way.items() if n >= _PER_WAY}
        links: Links = {}
        for x, sources in sorted(touched.items()):
            if is_source(x) or x in self.ends:
                add_link(links, x, Link(DIRECT_WEIGHT, 0, True))
            if x in over or len(sources) > THROUGH_CAP:
                continue
            for other in sorted(sources - {end, x}):
                add_link(links, other, Link(1 / math.log(len(sources)), 1, False))
        return links

    def top_steps(self, nodes: list[str], length: int) -> dict[str, Links]:
        """Of each of *nodes* its ``TOP_STEPS`` strongest steps, read once."""
        missing = [n for n in nodes if n not in self.top]
        if missing:
            read = _links(
                self.store.query(_TOP_STEPS_SQL, {"ids": missing, "top": TOP_STEPS})
            )
            for node in missing:
                self.top[node] = read.get(node, {})
        if any(len(self.top[n]) == TOP_STEPS for n in nodes):
            self._cut(length)
        return {n: self.top[n] for n in nodes}

    # ── the lengths ──────────────────────────────────────────────────────────

    def run(self, max_steps: int) -> None:
        a, b = self.ends
        left, right = self.steps_of(a), self.steps_of(b)
        one = left.get(b) or right.get(a)
        self.found.append([Found((), (one,))] if one else [])
        # the ends, and the sources the ends share
        used = {
            c for c in left.keys() & right.keys() if left[c].direct and right[c].direct
        } | set(self.ends)
        for length in range(2, max_steps + 1):
            if length == 2:
                found = [
                    Found((c,), (left[c], right[c]))
                    for c in sorted(left.keys() & right.keys())
                    if c not in used
                ]
            elif length == EXACT_STEPS:
                found = self._three(left, right, used)
            else:
                found = self._longer(left, right, used, length)
            self.found.append(found)
            used |= {s for chain in found for s in chain.between}

    def _three(self, left: Links, right: Links, used: set[str]) -> list[Found]:
        """Every chain of three steps: a step between a source of each end."""
        near = {c: link for c, link in left.items() if c not in used}
        far = {d: link for d, link in right.items() if d not in used}
        if max(len(near), len(far)) > LEVEL_CAP:
            self._cut(EXACT_STEPS)
        rows = self.store.query(
            _BETWEEN_SQL,
            {"near": strongest(near, LEVEL_CAP), "far": strongest(far, LEVEL_CAP)},
        )
        found = [
            Found((c, d), (near[c], link, far[d]))
            for c, steps in _links(rows).items()
            for d, link in steps.items()
            if c != d
        ]
        return sorted(found, key=lambda f: f.between)

    def _levels(
        self, start: Links, depth: int, blocked: set[str], length: int
    ) -> dict[str, Label]:
        """The sources *depth* steps from an end, each with the strongest way to it; the
        ``FRONTIER_CAP`` strongest of a level go on."""
        level = {
            c: Label((c,), (link,))
            for c, link in sorted(start.items())
            if c not in blocked
        }
        for _ in range(depth - 1):
            if len(level) > FRONTIER_CAP:
                self._cut(length)
            frontier = sorted(
                level, key=lambda n: (-level[n].strength[0], -level[n].strength[1], n)
            )[:FRONTIER_CAP]
            level = self._next(level, self.top_steps(frontier, length), blocked, length)
        return level

    def _next(
        self,
        level: dict[str, Label],
        steps: dict[str, Links],
        blocked: set[str],
        length: int,
    ) -> dict[str, Label]:
        """The level after *level*: from each source that goes on (*steps*), the strongest
        way to each source one step on."""
        found: dict[str, Label] = {}
        for node, onward in steps.items():
            for other, link in sorted(onward.items()):
                if other in blocked or other in level[node].path:
                    continue
                way = level[node].on(other, link)
                there = found.get(other)
                if there is not None:
                    self._cut(length)  # of two ways to a source one is kept
                    if there.strength >= way.strength:
                        continue
                found[other] = way
        return found

    def _longer(
        self, left: Links, right: Links, used: set[str], length: int
    ) -> list[Found]:
        """The chains of *length* steps where the levels from both ends meet."""
        near = (length + 1) // 2
        found, twice = meet(
            self._levels(left, near, used, length),
            self._levels(right, length - near, used, length),
        )
        if twice:
            self._cut(length)
        return found


# ── the ways of the steps shown ─────────────────────────────────────────────


@dataclass
class Ways:
    """What joins the two sources of a step: the edge between them, and the nodes they
    share (their sources, the node, its edge from the first and to the second)."""

    edge: str | None = None
    shared: list[tuple[int, str, str, str]] = field(default_factory=list)


def _read_ways(
    store: GraphStore, ends: tuple[str, str], pairs: list[tuple[str, str]]
) -> list[Ways]:
    found = [Ways() for _ in pairs]
    rows = store.query(
        _WAYS_SQL,
        {
            "firsts": [p[0] for p in pairs],
            "seconds": [p[1] for p in pairs],
            "ends": list(ends),
        },
    )
    for row in rows:
        ways = found[int(row["i"]) - 1]
        if row["x"] is None:
            ways.edge = row["from_first"]
        else:
            ways.shared.append(
                (int(row["sources"]), row["x"], row["from_first"], row["to_second"])
            )
    return found


def options_of(
    ends: tuple[str, str], chain: tuple[str, ...], i: int, link: Link, ways: Ways
) -> list[Step]:
    """The ways step *i* of *chain* may take, the best first: the edge, else of the nodes
    its sources share those with the fewest sources, then the lowest id, that are no
    source of the chain (at most ``_OPTIONS``)."""
    source, target = chain[i], chain[i + 1]
    count = link.ways + link.direct
    if ways.edge is not None:
        return [Step(source, target, None, (ways.edge,), count, link.weight)]
    # an end that is no source is one of the sources of what it shares
    plus = sum(1 for node in (source, target) if node in ends and not is_source(node))
    free = heapq.nsmallest(
        _OPTIONS,
        (
            (sources + plus, x, first, second)
            for sources, x, first, second in ways.shared
            if x not in chain and sources + plus <= THROUGH_CAP
        ),
    )
    return [
        Step(source, target, x, (first, second), count, link.weight)
        for _, x, first, second in free
    ]


def chain_of(sources: tuple[str, ...], options: list[list[Step]]) -> Chain | None:
    """The chain of *sources* whose steps take the best of their *options* such that no
    node is twice in it; None when there is none."""
    for steps in product(*options):
        vias = [s.via for s in steps if s.via is not None]
        if len(set(vias)) == len(vias):
            return Chain(sources, steps, min(s.weight for s in steps))
    return None


def _with_ways(
    store: GraphStore, ends: tuple[str, str], picked: list[Found]
) -> list[Chain | None]:
    """*picked* as chains, each step with its way; None for one with a step that has no
    way but through a node of the chain."""
    rows = [(ends[0], *f.between, ends[1]) for f in picked]
    pairs = [(row[i], row[i + 1]) for row in rows for i in range(len(row) - 1)]
    ways = iter(_read_ways(store, ends, pairs))
    return [
        chain_of(
            row,
            [
                options_of(ends, row, i, link, next(ways))
                for i, link in enumerate(found.links)
            ],
        )
        for row, found in zip(rows, picked, strict=True)
    ]


def pick(found: Iterable[Found], limit: int, taken: set[str]) -> list[Found]:
    """Of *found*, in their order, the first *limit* that pass no source another one of
    them or *taken* passes: each source between the ends once. Adds theirs to *taken*."""
    picked: list[Found] = []
    if limit <= 0:
        return picked
    for chain in found:
        if taken.isdisjoint(chain.between):
            picked.append(chain)
            taken.update(chain.between)
            if len(picked) == limit:
                break
    return picked


@dataclass
class _Showing:
    """The chains of a block shown so far, the rest in their order, and the sources they
    pass."""

    rest: Iterator[Found]
    shown: list[Chain] = field(default_factory=list)
    taken: set[str] = field(default_factory=set)


def _shown(
    store: GraphStore, ends: tuple[str, str], blocks: list[list[Found]], limit: int
) -> list[list[Chain]]:
    """Per block of *blocks* its first *limit* chains, the strongest first and each source
    between the ends once, each step with its way (one without a way passed over): the
    ways of every block read together."""
    showing = [_Showing(iter(sorted(found, key=Found.rank))) for found in blocks]
    while True:
        picked = [pick(s.rest, limit - len(s.shown), s.taken) for s in showing]
        flat = [chain for chains in picked for chain in chains]
        if not flat:
            return [s.shown for s in showing]
        ways = iter(_with_ways(store, ends, flat))
        for block, chains in zip(showing, picked, strict=True):
            for chain in chains:
                way = next(ways)
                if way is None:
                    block.taken.difference_update(chain.between)
                else:
                    block.shown.append(way)


def get_chains(
    store: GraphStore, ends: tuple[str, str], max_steps: int, limit: int
) -> Chains:
    """The chains from one of *ends* to the other of 1 to *max_steps* steps: per length a
    block with their number and the first *limit*, the strongest first, and every node and
    edge on those (a chain through a node that is not there left out). ``capped``: the
    search left a way out (a level at its cap, a source with more steps than it took, one
    of two ways to a source); ``partial``: it ran past ``CHAINS_BUDGET``. A block is
    ``complete`` when neither touched it."""
    search = _Search(store, ends)
    with read_budget(CHAINS_BUDGET, "The chains", reserve=CHAINS_RESERVE) as budget:
        search.run(max_steps)
    shown = _shown(store, ends, search.found, limit)
    blocks = []
    for steps in range(1, max_steps + 1):
        block = Block(steps)
        if steps <= len(search.found):
            block.total = len(search.found[steps - 1])
            block.chains = shown[steps - 1]
            block.complete = search.cut_at is None or steps < search.cut_at
        blocks.append(block)
    return _answer(store, blocks, search.cut_at is not None, budget.ran_out)


def _answer(
    store: GraphStore, blocks: list[Block], capped: bool, partial: bool
) -> Chains:
    """*blocks* with the nodes and edges of their chains; a chain through a node that is
    not there left out."""
    nodes = light_nodes(
        store, sorted({n for block in blocks for c in block.chains for n in _nodes(c)})
    )
    for block in blocks:
        block.chains = [c for c in block.chains if all(n in nodes for n in _nodes(c))]
    keys = sorted(
        {
            e
            for block in blocks
            for chain in block.chains
            for s in chain.steps
            for e in s.edges
        }
    )
    edges = (
        [light_edge_doc(row) for row in store.query(EDGES_SQL, {"keys": keys})]
        if keys
        else []
    )
    kept = sorted({n for block in blocks for c in block.chains for n in _nodes(c)})
    return Chains(blocks, [nodes[n] for n in kept], edges, capped, partial)


def _nodes(chain: Chain) -> tuple[str, ...]:
    """The sources of *chain* and the nodes its steps go through."""
    return (*chain.sources, *(s.via for s in chain.steps if s.via is not None))
