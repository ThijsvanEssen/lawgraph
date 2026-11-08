"""The course of a case (Verloop): the judgments of it in order, and the article of law that
gives each court its say (pure: no I/O, no store).

The judgments of a case are tied by ``APPEAL_OF``, ``REFERRED_BY`` and ``CONTINUES`` (from a
later judgment to an earlier one) and ``ADVISES_ON`` (from a conclusion to the judgment it
advises on). ``order_steps`` puts them in the order of the case: each edge says which of two
comes first, the date settles judgments of the same place. ``basis_of`` reads the article from
``data/route_articles.json``: by the tier of the court, the procedure and the area of law; a
step it does not know has none, never a guessed one.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from typing import Any

from lawgraph.config.constants import (
    DATA_DIR,
    RELATION_ADVISES_ON,
    RELATION_APPEAL_OF,
    RELATION_CONTINUES,
    RELATION_REFERRED_BY,
)

DATA = DATA_DIR / "route_articles.json"

# The relations of a course: from a later judgment to an earlier one, and ADVISES_ON from a
# conclusion to the judgment it advises on.
COURSE_RELATIONS = (
    RELATION_APPEAL_OF,
    RELATION_REFERRED_BY,
    RELATION_CONTINUES,
    RELATION_ADVISES_ON,
)
# The area of law of a judgment, from its ``subjects`` ("Bestuursrecht; Belastingrecht"): a
# tax case first, which the source files under Bestuursrecht.
_AREAS = (
    ("Belastingrecht", "belasting"),
    ("Civiel recht", "civiel"),
    ("Strafrecht", "straf"),
    ("Bestuursrecht", "bestuur"),
)


@dataclass(frozen=True)
class Edge:
    """An edge between two judgments of a case."""

    from_id: str
    to_id: str
    relation: str
    source_outcome: str | None = None


def area_of(subjects: Iterable[str] | None) -> str | None:
    """``civiel``, ``straf``, ``bestuur`` or ``belasting`` from the ``subjects`` of a
    judgment; None when they name none of them."""
    named = " ; ".join(subjects or ())
    return next((area for word, area in _AREAS if word in named), None)


@cache
def _rules() -> tuple[dict[str, Any], ...]:
    return tuple(json.loads(DATA.read_text(encoding="utf-8"))["rules"])


def basis_of(
    tier: str | None, procedure: str | None, area: str | None
) -> dict[str, str] | None:
    """``{bwb_id, article_number}`` of the first rule of ``data/route_articles.json`` the step
    fits: its tier, a procedure its own starts with (in any case) and its area. None for a
    step no rule fits."""
    if not (tier and procedure and area):
        return None
    written = procedure.casefold()
    for rule in _rules():
        if (
            tier in rule["tiers"]
            and area in rule["areas"]
            and any(written.startswith(p.casefold()) for p in rule["procedures"])
        ):
            return {"bwb_id": rule["bwb_id"], "article_number": rule["article_number"]}
    return None


def reach(
    start: str,
    edges_of: Callable[[list[str]], Iterable[Edge]],
    *,
    depth: int,
    limit: int,
) -> tuple[list[Edge], bool]:
    """The edges of the case of *start*, breadth-first both ways: ``edges_of(ids)`` gives
    the edges that touch any of *ids*. Up to *depth* edges from *start* and *limit*
    judgments; the second value whether the case goes on past them."""
    seen = {start}
    found: dict[tuple[str, str, str], Edge] = {}
    frontier = [start]
    truncated = False
    for _ in range(depth):
        if not frontier:
            break
        new: list[str] = []
        for edge in edges_of(frontier):
            for end in (edge.from_id, edge.to_id):
                if end in seen:
                    continue
                if len(seen) >= limit:
                    truncated = True
                    continue
                seen.add(end)
                new.append(end)
            if edge.from_id in seen and edge.to_id in seen:
                found.setdefault((edge.from_id, edge.to_id, edge.relation), edge)
        frontier = new
    if frontier and not truncated:
        truncated = any(
            e.from_id not in seen or e.to_id not in seen for e in edges_of(frontier)
        )
    return list(found.values()), truncated


def order_steps(
    start: str, edges: Sequence[Edge], dates: Mapping[str, str | None]
) -> list[str]:
    """The judgments of *edges* and *start* in the order of the case. A judgment comes after
    every earlier instance it names (its place one past the furthest of them, so a decision
    after referral that names the hof and the rechtbank comes after both); a conclusion
    half a place before the judgment it advises on. Judgments of one place by date, those
    without one first, then by id."""
    ids = {start} | {e.from_id for e in edges} | {e.to_id for e in edges}
    earlier = [e for e in edges if e.relation != RELATION_ADVISES_ON]
    place = dict.fromkeys(ids, 0.0)
    # the longest path to each, at most one pass per judgment (a cycle stops there)
    for _ in ids:
        moved = False
        for edge in earlier:
            if place[edge.from_id] < place[edge.to_id] + 1:
                place[edge.from_id] = place[edge.to_id] + 1
                moved = True
        if not moved:
            break
    for edge in edges:
        if edge.relation == RELATION_ADVISES_ON:
            place[edge.from_id] = place[edge.to_id] - 0.5
    return sorted(ids, key=lambda i: (place[i], dates.get(i) or "", i))
