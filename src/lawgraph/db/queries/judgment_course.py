"""The course of a case (``GET /api/judgments/{ecli}/course``): the judgments tied to one by
``core.judgment_course.COURSE_RELATIONS``, both ways, each with what a step shows. Reads
columns and ``lg_judgment_light`` only, never the props of a judgment (its text)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from lawgraph.config.constants import RELATION_REFERRED_BY
from lawgraph.core.courts import court_of
from lawgraph.core.ecli import court_code
from lawgraph.core.judgment_course import (
    COURSE_RELATIONS,
    Edge,
    area_of,
    basis_of,
    order_steps,
    reach,
)
from lawgraph.core.models import judgment_id
from lawgraph.db import GraphStore

# How far from the judgment asked for a course reaches: edges, and judgments in all.
COURSE_DEPTH = 8
COURSE_LIMIT = 24


@dataclass
class Course:
    """The steps of a course in order, the decisions the judgment asked for names in its
    text that are not loaded, and whether the case goes on past ``COURSE_DEPTH`` or
    ``COURSE_LIMIT``."""

    steps: list[dict[str, Any]] = field(default_factory=list)
    unresolved: list[dict[str, Any]] = field(default_factory=list)
    truncated: bool = False


def judgment_course(store: GraphStore, ecli: str) -> Course | None:
    """The course of the case of the judgment *ecli*; None when it is not in the graph."""
    start = judgment_id(ecli)
    rows = list(
        store.query(
            "SELECT id, props -> 'unresolved_appeal_targets' AS unresolved "
            "FROM judgments WHERE id = %(id)s",
            {"id": start},
        )
    )
    if not rows:
        return None
    edges, truncated = reach(
        start,
        lambda ids: _edges(store, ids),
        depth=COURSE_DEPTH,
        limit=COURSE_LIMIT,
    )
    nodes = _nodes(
        store, sorted({start} | {e.from_id for e in edges} | {e.to_id for e in edges})
    )
    order = order_steps(start, edges, {i: n.get("date") for i, n in nodes.items()})
    steps = [
        _step(nodes[i], [e for e in edges if e.from_id == i], nodes, current=i == start)
        for i in order
        if i in nodes
    ]
    return Course(
        steps=steps, unresolved=rows[0]["unresolved"] or [], truncated=truncated
    )


def _edges(store: GraphStore, ids: list[str]) -> list[Edge]:
    """The edges of a course that touch any of *ids*, either way, in a fixed order."""
    # one branch per end, each on its index (``edges_from_cover``, ``edges_to_cover``)
    rows = store.query(
        """
        SELECT e.from_id, e.to_id, e.relation,
               e.doc -> 'meta' ->> 'source_outcome' AS source_outcome
        FROM edges e
        WHERE e.from_id = ANY(%(ids)s::text[])
          AND e.relation = ANY(%(relations)s::text[]) AND e.to_collection = 'judgments'
        UNION
        SELECT e.from_id, e.to_id, e.relation,
               e.doc -> 'meta' ->> 'source_outcome' AS source_outcome
        FROM edges e
        WHERE e.to_id = ANY(%(ids)s::text[])
          AND e.relation = ANY(%(relations)s::text[]) AND e.from_collection = 'judgments'
        ORDER BY from_id NULLS LAST, to_id NULLS LAST, relation NULLS LAST
        """,
        {"relations": list(COURSE_RELATIONS), "ids": ids},
    )
    return [Edge(**row) for row in rows]


def _nodes(store: GraphStore, ids: list[str]) -> dict[str, dict[str, Any]]:
    """What a step shows of each judgment of *ids*, by id."""
    rows = store.query(
        """
        SELECT j.id, j.key, j.ecli, j.date_eff AS date, j.court_code, j.court, j.tier,
               j.court_kind, j.procedure, j.stub, j.subjects,
               j.pj_decision_kind #>> '{}' AS decision_kind,
               l.props ->> 'outcome' AS outcome
        FROM judgments j
        LEFT JOIN lg_judgment_light l ON l.id = j.id
        WHERE j.id = ANY(%(ids)s::text[])
        """,
        {"ids": ids},
    )
    return {row["id"]: row for row in rows}


def _step(
    node: dict[str, Any],
    edges: list[Edge],
    nodes: dict[str, dict[str, Any]],
    *,
    current: bool,
) -> dict[str, Any]:
    """One step: the judgment *node*, the article that gives its court its say, and its
    *edges* to earlier steps (of a conclusion: to the judgment it advises on). A decision
    after referral has no article: the source often names its procedure ``Hoger beroep``,
    but the court hears the case by the referral, which the list does not hold."""
    code = node["court_code"] or (court_code(node["ecli"]) if node["ecli"] else None)
    known = court_of(code, node["court"])
    tier = node["tier"] or (known.tier if known else None)
    area = area_of(node["subjects"])
    return {
        "ecli": node["ecli"],
        "key": node["key"],
        "court_code": code,
        "court_name": node["court"] or (known.name if known else None),
        "tier": tier,
        "court_kind": node["court_kind"] or (known.court_kind if known else None),
        "date": node["date"],
        "procedure": node["procedure"],
        "decision_kind": node["decision_kind"],
        "outcome": node["outcome"],
        "area": area,
        "basis": None
        if any(e.relation == RELATION_REFERRED_BY for e in edges)
        else basis_of(tier, node["procedure"], area),
        "loaded": not node["stub"],
        "current": current,
        "links": [
            {
                "relation": e.relation,
                "to": nodes[e.to_id]["ecli"],
                "source_outcome": e.source_outcome,
            }
            for e in edges
            if e.to_id in nodes
        ],
    }
