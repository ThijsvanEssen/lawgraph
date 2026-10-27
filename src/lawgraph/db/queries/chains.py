"""The chains between two chosen nodes (``GET /api/chains``): rows of one, two or three steps
from one to the other.

A *step* joins two sources: by an edge between them, or by a node with an edge to both (what
they share, as ``/api/nodes/shared`` finds it: a paper that names both, a judgment that cites
both). A *chain* is a row of steps from one end to the other; the sources between the ends
are laws and articles (``STEP_COLLECTIONS``), what two sources share can be any node. A chain
counts its steps, not its edges: two edges through a node both ends touch are one step. Each
node is once in a chain.

Of the chains of one length one per row of sources between the ends: each step names its
strongest way (the edge between its sources, else the node they share that is cited most,
then the lowest id) and how many ways it has. The shortest chains first: a source that a
shorter chain passes, or that the ends share, starts no longer chain. In a length the
heaviest first (the ``inbound_citation_count`` of its sources between the ends together),
then by their ids.

Read from both ends, one level at a time, as ``/api/paths`` reads its levels (``LEVEL_CAP``;
the ``PART_OF`` of an article and its law only where the law is an end, so that two articles
of one law are not one step apart): the neighbours of the ends, the sources next to those
(one step from an end), and the neighbours of those sources. No edge is derived.
"""

from __future__ import annotations

import heapq
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from itertools import product
from typing import Any

from lawgraph.config.constants import COLLECTION_ARTICLES, COLLECTION_INSTRUMENTS
from lawgraph.db import GraphStore
from lawgraph.db._rows import light_edge_doc
from lawgraph.db.queries.nodes import light_nodes
from lawgraph.db.queries.paths import EDGES_SQL, FOLLOWED
from lawgraph.db.store import read_budget

# The collections of the sources a chain passes between its ends.
STEP_COLLECTIONS = (COLLECTION_INSTRUMENTS, COLLECTION_ARTICLES)
MAX_STEPS = 3
LEVEL_CAP = 20_000  # the nodes one level keeps
_ROWS_PER_LEVEL = 100_000  # the edges read for one level, at most
PAIR_CAP = 50_000  # the chains of three steps found, at most
# How long the search may read (seconds): past it, the chains found by then (``partial``);
# what is left of the deadline of the request reads their nodes and edges.
CHAINS_BUDGET = 10.0
CHAINS_RESERVE = 3.0
# The ways of a step tried for a chain whose nodes must differ: more than the other nodes
# of the longest chain, so that one of them is always free.
_OPTIONS = 2 * MAX_STEPS + 1
# The ways of a step weighed for the chains of a page, at most (the first by id).
_WEIGHED = 1000

# Per node of the frontier its share of the level in the order of the covering indexes
# (``edges_from_cover``, ``edges_to_cover``), as ``/api/paths`` reads a level; ``far``
# keeps to the neighbours of those collections.
_NEIGHBORS_SQL = f"""
SELECT r.node, r.outbound, r.neighbor, r.key
FROM unnest(%(frontier)s::text[]) AS f(id)
CROSS JOIN LATERAL (
    (SELECT e.from_id AS node, TRUE AS outbound, e.to_id AS neighbor, e.key
     FROM edges e WHERE e.from_id = f.id {FOLLOWED}
       AND (%(far)s::text[] IS NULL OR e.to_collection = ANY(%(far)s))
     ORDER BY e.relation NULLS LAST, e.to_collection NULLS LAST, e.key NULLS LAST
     LIMIT %(share)s)
    UNION ALL
    (SELECT e.to_id, FALSE, e.from_id, e.key
     FROM edges e WHERE e.to_id = f.id {FOLLOWED}
       AND (%(far)s::text[] IS NULL OR e.from_collection = ANY(%(far)s))
     ORDER BY e.relation NULLS LAST, e.from_collection NULLS LAST, e.key NULLS LAST
     LIMIT %(share)s)
) r
WHERE r.neighbor <> r.node
ORDER BY 3 NULLS LAST, 4 NULLS LAST
LIMIT %(limit)s
"""

# How often each node is cited (0 for a node without a count), by key.
_CITED_SQL = f"""
SELECT x.id, coalesce(j.inbound_citation_count, a.inbound_citation_count,
                      lg_num(i.props -> 'inbound_citation_count'), 0) AS cited
FROM unnest(%(ids)s::text[]) AS x(id)
LEFT JOIN judgments j ON starts_with(x.id, 'judgments/') AND j.id = x.id
LEFT JOIN articles a ON starts_with(x.id, '{COLLECTION_ARTICLES}/') AND a.id = x.id
LEFT JOIN instruments i ON starts_with(x.id, '{COLLECTION_INSTRUMENTS}/') AND i.id = x.id
"""

# Per way of a step: the node its sources share (None: the edge between them) and its
# edges, from the first source of the step.
Ways = dict[str | None, tuple[str, ...]]
# Per neighbour of a node the edge between them (the lowest key).
Around = dict[str, dict[str, str]]


@dataclass(frozen=True)
class Step:
    """One step of a chain: from *source* to *target* by the edge between them (``via``
    None) or through the node they share, its edges in that order, and how many ways the
    step has (``ways``: that edge and each node they share)."""

    source: str
    target: str
    via: str | None
    edges: tuple[str, ...]
    ways: int


@dataclass(frozen=True)
class Chain:
    """The sources of a chain from one end to the other, its steps and its weight."""

    sources: tuple[str, ...]
    steps: tuple[Step, ...]
    weight: int


@dataclass
class Block:
    """The chains of one length: *total* of them, the first *limit* in ``chains``;
    ``complete`` when the search read all it needed for them."""

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


def _is_source(node: str) -> bool:
    return node.split("/", 1)[0] in STEP_COLLECTIONS


class _Search:
    """The chains of two ends by their length, found so far: per length the ways of each
    step per row of sources between the ends (those of the last step of a longer chain as
    read from the far end: its edges in the other order)."""

    def __init__(self, store: GraphStore, ends: tuple[str, str]) -> None:
        self.store = store
        self.ends = ends
        self.found: list[dict[tuple[str, ...], list[Ways]]] = []
        # the first length whose reads were cut (a level at its cap, the pairs at theirs)
        self.cut_at: int | None = None

    def _cut(self, length: int) -> None:
        self.cut_at = length if self.cut_at is None else min(self.cut_at, length)

    def around(
        self, frontier: Iterable[str], length: int, far: Iterable[str] | None
    ) -> Around:
        """Per node of *frontier* its neighbours (of the collections *far* alone, when
        given), each with the lowest key of the edges between them."""
        nodes = sorted(set(frontier))
        if not nodes:
            return {}
        share = -(-_ROWS_PER_LEVEL // len(nodes))
        rows = list(
            self.store.query(
                _NEIGHBORS_SQL,
                {
                    "frontier": nodes,
                    "far": list(far) if far is not None else None,
                    "limit": _ROWS_PER_LEVEL,
                    "share": share,
                    "relations": None,
                    "through_laws": False,
                    "ends": list(self.ends),
                },
                index_order=True,
            )
        )
        # the level, or the edges of a node one way, cut at their limit
        if (
            len(rows) == _ROWS_PER_LEVEL
            or share in Counter((row["node"], row["outbound"]) for row in rows).values()
        ):
            self._cut(length)
        found: Around = {}
        level: set[str] = set()
        for row in rows:
            neighbor = row["neighbor"]
            if neighbor not in level:
                if len(level) == LEVEL_CAP:
                    self._cut(length)
                    break
                level.add(neighbor)
            found.setdefault(row["node"], {}).setdefault(neighbor, row["key"])
        return found

    def sources(self, near: dict[str, str], nexts: Around) -> dict[str, Ways]:
        """The sources one step from the end whose neighbours are *near*, with the ways
        from the end to each."""
        found: dict[str, Ways] = {}
        for node, edge in near.items():
            if node in self.ends:
                continue
            if _is_source(node):
                found.setdefault(node, {})[None] = (edge,)
            for source, onward in nexts.get(node, {}).items():
                if source not in self.ends:
                    found.setdefault(source, {}).setdefault(node, (edge, onward))
        return found

    def run(self, max_steps: int) -> None:
        a, b = self.ends
        near = self.around(self.ends, 1, None)
        near_a, near_b = near.get(a, {}), near.get(b, {})
        one: Ways = {k: (near_a[k], near_b[k]) for k in near_a.keys() & near_b.keys()}
        if b in near_a:
            one[None] = (near_a[b],)
        self.found.append({(): [one]} if one else {})
        if max_steps == 1:
            return
        used: set[str] = {k for k in one if k is not None}
        nexts = self.around(
            (near_a.keys() | near_b.keys()) - set(self.ends), 2, STEP_COLLECTIONS
        )
        left, right = self.sources(near_a, nexts), self.sources(near_b, nexts)
        self.found.append(
            {
                (c,): [left[c], right[c]]
                for c in left.keys() & right.keys()
                if c not in used
            }
        )
        if max_steps == 2:
            return
        used |= {c for (c,) in self.found[1]}
        left = {c: ways for c, ways in left.items() if c not in used}
        right = {d: ways for d, ways in right.items() if d not in used}
        far = self.around(left.keys() | right.keys(), 3, None)
        middle = self.middle(left, right, far)
        self.found.append(
            {(c, d): [left[c], ways, right[d]] for (c, d), ways in middle.items()}
        )

    def middle(
        self, left: dict[str, Ways], right: dict[str, Ways], far: Around
    ) -> dict[tuple[str, str], Ways]:
        """Per source of *left* and of *right* one step apart: the ways between them."""
        # the nodes next to a source of the right, with the edge from each to it
        toward: Around = {}
        for d in right:
            for node, edge in far.get(d, {}).items():
                toward.setdefault(node, {})[d] = edge
        found: dict[tuple[str, str], Ways] = {}
        for c in sorted(left):
            for node, edge in sorted(far.get(c, {}).items()):
                if node in self.ends:
                    continue
                ways: list[tuple[str, str | None, tuple[str, ...]]] = (
                    [(node, None, (edge,))] if node in right else []
                )
                ways += [
                    (d, node, (edge, onward))
                    for d, onward in toward.get(node, {}).items()
                    if d != c
                ]
                for d, via, edges in ways:
                    if (c, d) not in found and len(found) == PAIR_CAP:
                        self._cut(3)
                        return found
                    found.setdefault((c, d), {}).setdefault(via, edges)
        return found


class _Options:
    """The ways of a step tried for a chain, best by *rank* first, read once per step (a
    source one step from an end is in many chains)."""

    def __init__(self, rank: Callable[[str | None], Any]) -> None:
        self.rank = rank
        # by the id of the ways, kept with them so that the id is not another's
        self.read: dict[int, tuple[Ways, list[str | None]]] = {}

    def of(self, ways: Ways) -> list[str | None]:
        if id(ways) not in self.read:
            self.read[id(ways)] = ways, heapq.nsmallest(_OPTIONS, ways, key=self.rank)
        return self.read[id(ways)][1]

    def pick(
        self, sources: tuple[str, ...], steps: list[Ways]
    ) -> tuple[str | None, ...] | None:
        """Per step the way to take, the best first, such that no node is twice in the
        chain; None when there is none."""
        for pick in product(*(self.of(ways) for ways in steps)):
            vias = [via for via in pick if via is not None]
            if len(set(vias)) == len(vias) and set(sources).isdisjoint(vias):
                return pick
        return None


def _by_id(via: str | None) -> tuple[bool, str]:
    return via is not None, via or ""


def _cited(store: GraphStore, ids: Iterable[str]) -> dict[str, int]:
    wanted = sorted(set(ids))
    if not wanted:
        return {}
    rows = store.query(_CITED_SQL, {"ids": wanted})
    return {row["id"]: int(row["cited"]) for row in rows}


def _chain(
    sources: tuple[str, ...],
    steps: list[Ways],
    pick: tuple[str | None, ...],
    weight: int,
) -> Chain:
    last = len(steps) - 1
    return Chain(
        sources=sources,
        steps=tuple(
            Step(
                sources[i],
                sources[i + 1],
                via,
                # the last step of a longer chain was read from the far end
                steps[i][via][::-1] if 0 < i == last else steps[i][via],
                len(steps[i]),
            )
            for i, via in enumerate(pick)
        ),
        weight=weight,
    )


def _block(
    store: GraphStore,
    ends: tuple[str, str],
    found: dict[tuple[str, ...], list[Ways]],
    limit: int,
) -> tuple[int, list[Chain]]:
    """The number of chains of *found* whose nodes can all differ, and the first *limit*
    of them, the heaviest first."""
    any_way = _Options(_by_id)
    possible = [
        between
        for between, steps in found.items()
        if any_way.pick((*ends, *between), steps) is not None
    ]
    weights = _cited(store, (s for between in possible for s in between))

    def weight(between: tuple[str, ...]) -> int:
        return sum(weights.get(s, 0) for s in between)

    possible.sort(key=lambda between: (-weight(between), between))
    kept = possible[:limit]
    # of the ways of each step the most cited (of its first ``_WEIGHED`` by id)
    vias = _cited(
        store,
        (
            via
            for between in kept
            for ways in found[between]
            for via in heapq.nsmallest(_WEIGHED, ways, key=_by_id)
            if via is not None
        ),
    )
    best = _Options(lambda via: (via is not None, -vias.get(via or "", 0), via or ""))
    chains = []
    for between in kept:
        sources = (ends[0], *between, ends[1])
        pick = best.pick(sources, found[between])
        if pick is not None:
            chains.append(_chain(sources, found[between], pick, weight(between)))
    return len(possible), chains


def get_chains(
    store: GraphStore, ends: tuple[str, str], max_steps: int, limit: int
) -> Chains:
    """The chains from one of *ends* to the other of 1 to *max_steps* steps: per length a
    block with their number and the first *limit*, the heaviest first, and every node and
    edge on those (a chain through a node that is not there left out). ``capped``: a
    level or the pairs of three steps reached its cap; ``partial``: the search ran past
    ``CHAINS_BUDGET``. A block is ``complete`` when neither touched it."""
    search = _Search(store, ends)
    with read_budget(CHAINS_BUDGET, "The chains", reserve=CHAINS_RESERVE) as budget:
        search.run(max_steps)
    blocks = []
    for steps in range(1, max_steps + 1):
        block = Block(steps)
        if steps <= len(search.found):
            block.total, block.chains = _block(
                store, ends, search.found[steps - 1], limit
            )
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
