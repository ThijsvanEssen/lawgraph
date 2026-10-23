"""The surroundings of a paper, a case, a vote, a commitment or an activity
(``GET /api/nodes/{collection}/{key}/surroundings``): who put it forward, the dossier it
belongs to as one node with what that holds counted, the laws it touches, the votes on it
per faction, and what follows from it, each section a few nodes and a total.

Every read is a handful of edges of the focal node and of its case or paper, by the
covering indexes (``edges_from_cover``, ``edges_to_cover``): a paper of a dossier of
10,000 documents costs what a paper of a small one costs, since the dossier is counted and
never walked.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Literal

from lawgraph.config.constants import (
    CHANGE_RELATIONS,
    COLLECTION_ACTIVITIES,
    COLLECTION_ARTICLES,
    COLLECTION_CASES,
    COLLECTION_COMMITMENTS,
    COLLECTION_COMMITTEES,
    COLLECTION_DECISIONS,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_FACTIONS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_MEMBERS,
    RELATION_ABOUT,
    RELATION_ANSWERS,
    RELATION_AUTHORED,
    RELATION_LED_BY,
    RELATION_LEGISLATED_IN,
    RELATION_MADE_IN,
    RELATION_MEMBER_OF,
    RELATION_PART_OF,
    RELATION_REFERS_TO,
    RELATION_REVISES,
    RELATION_VOTED,
)
from lawgraph.db import GraphStore
from lawgraph.db.queries.nodes import light_nodes
from lawgraph.db.queries.not_found import NotFound

# What can be the focal node: the sources a reader asks "what is around this?" of.
SURROUNDED = (
    COLLECTION_DOCUMENTS,
    COLLECTION_CASES,
    COLLECTION_DECISIONS,
    COLLECTION_COMMITMENTS,
    COLLECTION_ACTIVITIES,
)

DEFAULT_CAP = 10
MAX_CAP = 50
# The most a section reads at one node before it picks its ``cap``: the documents of a case,
# the decisions on a paper.
_READ_PER_NODE = 50

Side = Literal["out", "in"]

# What the laws section follows from a paper, nearest first: what it changes, the law its
# dossier became, then what it only names.
_CHANGES = CHANGE_RELATIONS
_LAW_ORDER = (*_CHANGES, RELATION_LEGISLATED_IN, RELATION_REFERS_TO)
_LAWS = (COLLECTION_ARTICLES, COLLECTION_INSTRUMENTS)


@dataclass(frozen=True)
class Reach:
    """Which edges to read at a set of nodes: of *relations*, leaving them (``out``) or
    reaching them (``in``), to or from a node of *collections* (all when null); *meta*
    the keys of the edge's ``meta`` it needs."""

    relations: tuple[str, ...]
    side: Side
    collections: tuple[str, ...] | None = None
    meta: tuple[str, ...] = ()


@dataclass(frozen=True)
class Hit:
    """One edge read: *node* is the end asked for, *other* the node at its other end."""

    node: str
    other: str
    collection: str
    relation: str
    side: Side
    edge: str
    status: str | None
    meta: dict[str, Any]


@dataclass(frozen=True)
class Kind:
    """How many edges of a relation reach nodes of a collection."""

    relation: str
    collection: str
    count: int


@dataclass
class Section:
    """A section: its hits (at most ``cap``), their total and the total per kind."""

    hits: list[Hit] = field(default_factory=list)
    total: int = 0
    kinds: list[Kind] = field(default_factory=list)


@dataclass(frozen=True)
class Ask:
    """A read: the edges of *reach* at each of *ids*, at most *limit* per node."""

    ids: list[str]
    reach: Reach
    limit: int = _READ_PER_NODE


def _ends(side: Side) -> tuple[str, str]:
    """The column of the node asked for and that of the other end."""
    return ("from", "to") if side == "out" else ("to", "from")


def _select(ask: Ask, n: int, counting: bool) -> str:
    """SQL: the read of *ask*, whose parameters are numbered *n*."""
    reach = ask.reach
    own, other = _ends(reach.side)
    collections = (
        f"AND e.{other}_collection = ANY(%(collections_{n})s)"
        if reach.collections
        else ""
    )
    if counting:
        return f"""
        SELECT {n} AS ask, e.relation, e.{other}_collection AS collection,
               count(*)::int AS n
        FROM edges e
        WHERE e.{own}_id = ANY(%(ids_{n})s) AND e.relation = ANY(%(relations_{n})s)
              {collections}
        GROUP BY 1, 2, 3"""
    meta = ", ".join(f"'{k}', e.doc #> '{{meta,{k}}}'" for k in reach.meta)
    return f"""
    SELECT {n} AS ask, f.id AS node, r.other, r.collection, r.relation, r.edge, r.status,
           r.meta
    FROM unnest(%(ids_{n})s::text[]) AS f(id)
    CROSS JOIN LATERAL (
        SELECT e.{other}_id AS other, e.{other}_collection AS collection, e.relation,
               e.key AS edge, e.status, json_build_object({meta}) AS meta
        FROM edges e
        WHERE e.{own}_id = f.id AND e.relation = ANY(%(relations_{n})s) {collections}
        ORDER BY array_position(%(relations_{n})s::text[], e.relation),
                 e.{other}_collection, e.key
        LIMIT %(limit_{n})s) r"""


def _batch(asks: list[Ask], counting: bool) -> tuple[str, dict[str, Any]]:
    params: dict[str, Any] = {}
    for n, ask in enumerate(asks):
        params[f"ids_{n}"] = ask.ids
        params[f"relations_{n}"] = list(ask.reach.relations)
        params[f"limit_{n}"] = ask.limit
        if ask.reach.collections:
            params[f"collections_{n}"] = list(ask.reach.collections)
    statement = " UNION ALL ".join(
        f"({_select(a, n, counting)})" for n, a in enumerate(asks)
    )
    return statement, params


def read_all(store: GraphStore, asks: dict[str, Ask]) -> dict[str, list[Hit]]:
    """The edges of every ask, in one statement, by the name of the ask (an ask without
    ids finds none)."""
    names = [n for n, ask in asks.items() if ask.ids]
    found: dict[str, list[Hit]] = {name: [] for name in asks}
    if not names:
        return found
    statement, params = _batch([asks[n] for n in names], False)
    for row in store.query(statement, params):
        name = names[row["ask"]]
        found[name].append(
            Hit(
                row["node"],
                row["other"],
                row["collection"],
                row["relation"],
                asks[name].reach.side,
                row["edge"],
                row["status"],
                row["meta"] or {},
            )
        )
    return found


def count_all(store: GraphStore, asks: dict[str, Ask]) -> dict[str, list[Kind]]:
    """How many edges every ask has at its ids together, per relation and collection, in
    one statement."""
    names = [n for n, ask in asks.items() if ask.ids]
    found: dict[str, list[Kind]] = {name: [] for name in asks}
    if not names:
        return found
    statement, params = _batch([asks[n] for n in names], True)
    for row in store.query(statement, params):
        found[names[row["ask"]]].append(
            Kind(row["relation"], row["collection"], row["n"])
        )
    return found


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _ids(hits: list[Hit], collection: str | None = None) -> list[str]:
    return _unique(h.other for h in hits if collection in (None, h.collection))


def _merge(
    hits: dict[str, list[Hit]],
    kinds: dict[str, list[Kind]],
    names: tuple[str, ...],
    cap: int,
    order: tuple[str, ...] = (),
) -> Section:
    """The asks *names* as one section: their hits by the relation order *order* (the
    order of the asks without it), each node once per relation, at most *cap*, and the
    total of their edges."""
    found = [h for n in names for h in hits[n]]
    position = {r: i for i, r in enumerate(order)} if order else {}
    ranks = {id(h): position.get(h.relation, len(position)) for h in found}
    seen: set[tuple[str, str]] = set()
    kept: list[Hit] = []
    for hit in sorted(found, key=lambda h: (ranks[id(h)], h.collection, h.other)):
        if (hit.other, hit.relation) not in seen:
            seen.add((hit.other, hit.relation))
            kept.append(hit)
    counted = [k for n in names for k in kinds[n]]
    return Section(kept[:cap], sum(k.count for k in counted), counted)


# ── the sections ──────────────────────────────────────────────────────────────

_PART_OF_DOSSIER = Reach((RELATION_PART_OF,), "out", (COLLECTION_DOSSIERS,))
_PART_OF_CASE = Reach((RELATION_PART_OF,), "out", (COLLECTION_CASES,))
_ABOUT = Reach(
    (RELATION_ABOUT,),
    "out",
    (COLLECTION_DOCUMENTS, COLLECTION_CASES, COLLECTION_DOSSIERS),
)
_ABOUT_DOSSIER = Reach((RELATION_ABOUT,), "out", (COLLECTION_DOSSIERS,))
_DECIDED_ON = Reach((RELATION_ABOUT,), "in", (COLLECTION_DECISIONS,))
_SIGNED_BY = Reach(
    (RELATION_AUTHORED,),
    "in",
    (COLLECTION_MEMBERS,),
    ("role", "function", "capacity"),
)
_MEMBER_OF_FACTION = Reach(
    (RELATION_MEMBER_OF,), "out", (COLLECTION_FACTIONS,), ("from_date", "to_date")
)
_VOTED = Reach((RELATION_VOTED,), "in", (COLLECTION_FACTIONS,), ("choice", "seats"))

# What a dossier holds, counted by the edges that reach it: (relation, collection of the
# source) -> name.
_HELD = {
    (RELATION_PART_OF, COLLECTION_DOCUMENTS): "documents",
    (RELATION_PART_OF, COLLECTION_CASES): "cases",
    (RELATION_ABOUT, COLLECTION_DECISIONS): "decisions",
    (RELATION_ABOUT, COLLECTION_COMMITMENTS): "commitments",
    (RELATION_ABOUT, COLLECTION_ACTIVITIES): "activities",
    (RELATION_LEGISLATED_IN, COLLECTION_INSTRUMENTS): "laws",
}


@dataclass
class Surroundings:
    """The surroundings of one node: the hits of its sections and the nodes they name."""

    focal: str
    submitters: Section = field(default_factory=Section)
    # the faction each submitter sat in on the day of the node (member id -> faction id)
    factions: dict[str, str] = field(default_factory=dict)
    dossiers: Section = field(default_factory=Section)
    # per dossier shown: how many of each source it holds (``_HELD``)
    held: dict[str, dict[str, int]] = field(default_factory=dict)
    laws: Section = field(default_factory=Section)
    # the decisions on it, newest first, the node each is about, and their total
    votes: list[str] = field(default_factory=list)
    votes_about: dict[str, str] = field(default_factory=dict)
    votes_total: int = 0
    # per decision shown: the vote of each faction
    by_faction: dict[str, list[Hit]] = field(default_factory=dict)
    follows: Section = field(default_factory=Section)
    context: Section = field(default_factory=Section)
    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    notes: dict[str, Any] = field(default_factory=dict)


def _stand_for(
    store: GraphStore, focal: str, collection: str
) -> tuple[list[str], list[str], list[str]]:
    """The documents, the cases and the dossiers the focal node stands for: what the
    sections look at besides the node itself."""
    if collection == COLLECTION_DOCUMENTS:
        found = read_all(
            store,
            {
                "cases": Ask([focal], _PART_OF_CASE),
                "dossiers": Ask([focal], _PART_OF_DOSSIER),
            },
        )
        return [focal], _ids(found["cases"]), _ids(found["dossiers"])
    if collection == COLLECTION_CASES:
        found = read_all(
            store,
            {
                "documents": Ask(
                    [focal], Reach((RELATION_PART_OF,), "in", (COLLECTION_DOCUMENTS,))
                ),
                "dossiers": Ask([focal], _PART_OF_DOSSIER),
            },
        )
        return _ids(found["documents"]), [focal], _ids(found["dossiers"])
    about = read_all(store, {"about": Ask([focal], _ABOUT)})["about"]
    cases, dossiers = _ids(about, COLLECTION_CASES), _ids(about, COLLECTION_DOSSIERS)
    if collection == COLLECTION_DECISIONS:
        return _ids(about, COLLECTION_DOCUMENTS), cases, dossiers
    return [], cases, dossiers


def _asks(
    focal: str,
    collection: str,
    documents: list[str],
    cases: list[str],
    dossiers: list[str],
) -> dict[str, Ask]:
    """Every read the sections make once the documents, cases and dossiers are known."""
    own = _unique([focal, *documents])
    # who signed the paper or case, made the commitment, or signed what a vote is on
    signed = {
        COLLECTION_DOCUMENTS: [focal],
        COLLECTION_CASES: [focal],
        COLLECTION_COMMITMENTS: [focal],
        COLLECTION_DECISIONS: documents or cases,
    }.get(collection, [])
    decided = {
        COLLECTION_ACTIVITIES: Ask(
            [focal], Reach((RELATION_MADE_IN,), "in", (COLLECTION_DECISIONS,))
        ),
        COLLECTION_DECISIONS: Ask([], _DECIDED_ON),
        COLLECTION_COMMITMENTS: Ask([], _DECIDED_ON),
    }.get(collection, Ask([*documents, *cases], _DECIDED_ON))
    asks = {
        "submitters": Ask(signed, _SIGNED_BY, MAX_CAP * 2),
        "dossier_part": Ask(own, _PART_OF_DOSSIER),
        "dossier_about": Ask(own, _ABOUT_DOSSIER),
        "laws_own": Ask(
            documents, Reach((*_CHANGES, RELATION_REFERS_TO), "out", _LAWS), MAX_CAP
        ),
        "laws_made": Ask(
            dossiers,
            Reach((RELATION_LEGISLATED_IN,), "in", (COLLECTION_INSTRUMENTS,)),
            MAX_CAP,
        ),
        "debate": Ask(
            own, Reach((RELATION_MADE_IN,), "out", (COLLECTION_ACTIVITIES,)), MAX_CAP
        ),
        "lead": Ask(
            _unique([focal, *cases]),
            Reach((RELATION_LED_BY,), "out", (COLLECTION_COMMITTEES,)),
            MAX_CAP,
        ),
        "votes": decided,
    }
    return asks | _follow_asks(focal, collection, documents)


def _follow_asks(focal: str, collection: str, documents: list[str]) -> dict[str, Ask]:
    """What follows directly: the commitments a letter fulfils, the letters that answer
    the paper, the paper that replaces it; of a commitment the letters that fulfil it; of
    an activity what was made in it."""
    if collection == COLLECTION_ACTIVITIES:
        made = (COLLECTION_COMMITMENTS, COLLECTION_DOCUMENTS)
        return {"made": Ask([focal], Reach((RELATION_MADE_IN,), "in", made))}
    if collection == COLLECTION_COMMITMENTS:
        letters = Reach((RELATION_ANSWERS,), "in", (COLLECTION_DOCUMENTS,))
        return {"letters": Ask([focal], letters)}
    return {
        "fulfils": Ask(
            documents, Reach((RELATION_ANSWERS,), "out", (COLLECTION_COMMITMENTS,))
        ),
        "answered": Ask(
            documents, Reach((RELATION_ANSWERS,), "in", (COLLECTION_DOCUMENTS,))
        ),
        "replaced": Ask(
            documents, Reach((RELATION_REVISES,), "in", (COLLECTION_DOCUMENTS,))
        ),
    }


def _dossier_counts(
    store: GraphStore, dossiers: list[str]
) -> dict[str, dict[str, int]]:
    """Per dossier how many documents, cases, decisions, commitments, activities and laws it
    holds, from the index of its edges alone."""
    counts = {d: dict.fromkeys(_HELD.values(), 0) for d in dossiers}
    if dossiers:
        rows = store.query(
            """
            SELECT e.to_id AS dossier, e.relation, e.from_collection AS collection,
                   count(*)::int AS n
            FROM edges e
            WHERE e.to_id = ANY(%(ids)s) AND e.relation = ANY(%(relations)s)
            GROUP BY 1, 2, 3""",
            {"ids": dossiers, "relations": sorted({r for r, _ in _HELD})},
        )
        for row in rows:
            name = _HELD.get((row["relation"], row["collection"]))
            if name:
                counts[row["dossier"]][name] = row["n"]
    return counts


def _faction_on(hits: list[Hit], day: str | None) -> dict[str, str]:
    """The faction each member of *hits* (their ``MEMBER_OF`` edges) sat in on *day*
    (without a day: the one they sit in now); none for a member without one."""
    found: dict[str, str] = {}
    for hit in hits:
        start, end = hit.meta.get("from_date"), hit.meta.get("to_date")
        if day is None:
            within = end is None
        else:
            within = (start is None or start <= day) and (end is None or end >= day)
        if within:
            found.setdefault(hit.node, hit.other)
    return found


def _first_signer_first(found: Section, cap: int) -> None:
    """Keep of *found* each member once, the first signatory first, at most *cap*."""
    ranked = sorted(
        found.hits,
        key=lambda h: (not str(h.meta.get("role") or "").startswith("Eerste"), h.other),
    )
    once = {h.other: h for h in reversed(ranked)}
    found.hits = [h for h in ranked if once[h.other] is h][:cap]


def _date(node: dict[str, Any] | None) -> str:
    value = ((node or {}).get("props") or {}).get("date")
    return value if isinstance(value, str) else ""


def get_surroundings(
    store: GraphStore, collection: str, key: str, cap: int = DEFAULT_CAP
) -> Surroundings:
    """The surroundings of the node ``collection/key``; ``NotFound`` when it is not there.
    The caller has checked that *collection* is one of ``SURROUNDED``."""
    focal = f"{collection}/{key}"
    nodes = light_nodes(store, [focal])
    if focal not in nodes:
        raise NotFound("Node", focal)
    documents, cases, dossier_ids = _stand_for(store, focal, collection)
    asks = _asks(focal, collection, documents, cases, dossier_ids)
    hits, kinds = read_all(store, asks), count_all(store, asks)
    result = Surroundings(focal)

    result.submitters = _merge(hits, kinds, ("submitters",), MAX_CAP * 2)
    _first_signer_first(result.submitters, cap)
    result.dossiers = _merge(hits, kinds, ("dossier_part", "dossier_about"), cap)
    result.laws = _merge(hits, kinds, ("laws_own", "laws_made"), cap, _LAW_ORDER)
    follow = tuple(n for n in _follow_asks(focal, collection, documents))
    result.follows = _merge(hits, kinds, follow, cap)
    result.context = _merge(hits, kinds, ("debate", "lead"), cap)
    result.held = _dossier_counts(store, _ids(result.dossiers.hits))

    voted = _merge(hits, kinds, ("votes",), MAX_CAP)
    decisions = [focal] if collection == COLLECTION_DECISIONS else _ids(voted.hits)
    result.votes_total = 1 if collection == COLLECTION_DECISIONS else voted.total
    result.votes_about = {h.other: h.node for h in voted.hits}
    members = _ids(result.submitters.hits)
    shown = [
        *decisions,
        *members,
        *(
            h.other
            for s in (result.dossiers, result.laws, result.follows, result.context)
            for h in s.hits
        ),
    ]
    nodes.update(light_nodes(store, [i for i in _unique(shown) if i not in nodes]))
    result.votes = sorted(
        decisions, key=lambda d: (_date(nodes.get(d)), d), reverse=True
    )[:cap]

    # how each faction voted on the decisions shown, and where the signers sat that day
    later = read_all(
        store,
        {
            "voted": Ask(result.votes, _VOTED, 40),
            "member_of": Ask(members, _MEMBER_OF_FACTION, 20),
        },
    )
    for hit in later["voted"]:
        result.by_faction.setdefault(hit.node, []).append(hit)
    day = _date(nodes.get(focal)) or None
    result.factions = _faction_on(later["member_of"], day)
    named = [h.other for hs in result.by_faction.values() for h in hs]
    named += result.factions.values()
    nodes.update(light_nodes(store, [i for i in _unique(named) if i not in nodes]))
    result.nodes = nodes
    return result
