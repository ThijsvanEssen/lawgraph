"""The rules every cabinet must meet, and what its seats and phases show.

``violations`` lists what breaks a rule, for any cabinet:

- every post lies within the cabinet's period, a stand-in included;
- no two holders of one seat overlap unless both carry ``overlaps_with`` (the shared seat of
  the viceminister-president aside);
- every successor in a seat starts on or after its predecessor's (corrected) end, unless
  the two carry ``overlaps_with``;
- the phases are ordered, do not overlap and cover the cabinet from its start to its end
  (or to now): a ``formatie`` before the start, then one after another.

``cabinet_row`` is one row of ``lawgraph verify cabinets``.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from lawgraph.core.cabinet_phases import KIND_FORMATION, KIND_IN_OFFICE
from lawgraph.core.cabinet_posts import (
    CORRECTED_BY_PREDECESSOR,
    CORRECTED_BY_SUCCESSOR,
    CORRECTED_TO_CABINET,
    SEAT_DEPUTY,
    seat_gaps,
)

_OPEN = "9999-12-31"


def _by_seat(posts: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    seats: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for post in posts:
        if post.get("seat") != SEAT_DEPUTY:
            seats[post.get("seat") or ""].append(post)
    for held in seats.values():
        held.sort(key=lambda p: (p["from_date"] or "", p["to_date"] or _OPEN))
    return seats


def _who(post: dict[str, Any]) -> str:
    return str(post.get("member") or post.get("person") or post.get("name"))


def _post_violations(cabinet: dict[str, Any], posts: list[dict[str, Any]]) -> list[str]:
    start, end = cabinet["from_date"], cabinet["to_date"] or _OPEN
    found = []
    for post in posts:
        to = post["to_date"] or _OPEN
        if not post["from_date"] or post["from_date"] < start or to > end:
            found.append(
                f"{cabinet['key']}: {_who(post)} in {post['seat']} "
                f"{post['from_date']}–{post['to_date']} lies outside the cabinet"
            )
        if (
            post["from_date"]
            and post["to_date"]
            and post["to_date"] < post["from_date"]
        ):
            found.append(
                f"{cabinet['key']}: {_who(post)} in {post['seat']} ends before it starts"
            )
    for seat, held in _by_seat(posts).items():
        for i, a in enumerate(held):
            for b in held[i + 1 :]:
                if _who(a) == _who(b):
                    continue
                if b["from_date"] < (a["to_date"] or _OPEN) and not (
                    a.get("overlaps_with") and b.get("overlaps_with")
                ):
                    found.append(
                        f"{cabinet['key']}: {_who(b)} starts in {seat} on "
                        f"{b['from_date']} before {_who(a)} ends ({a['to_date']}) "
                        "without overlaps_with"
                    )
    return found


def _phase_violations(cabinet: dict[str, Any]) -> list[str]:
    phases = cabinet.get("phases") or []
    if not phases:
        return []
    key = cabinet["key"]
    found = []
    term = [p for p in phases if p["kind"] != KIND_FORMATION]
    formation = [p for p in phases if p["kind"] == KIND_FORMATION]
    if formation and (phases[0] is not formation[0] or len(formation) > 1):
        found.append(f"{key}: the formatie is not the one first phase")
    if formation and formation[0]["to_date"] != cabinet["from_date"]:
        found.append(f"{key}: the formatie does not end at the start")
    if not term or term[0]["from_date"] != cabinet["from_date"]:
        found.append(f"{key}: the phases do not begin at the start of the cabinet")
    for a, b in zip(phases, phases[1:], strict=False):
        if a["to_date"] != b["from_date"] or (a["from_date"] or "") > (
            b["from_date"] or ""
        ):
            found.append(f"{key}: phase {a['kind']} and {b['kind']} do not follow")
    if term and term[-1]["to_date"] != cabinet["to_date"]:
        found.append(f"{key}: the phases do not end with the cabinet")
    return found


def violations(cabinet: dict[str, Any], posts: list[dict[str, Any]]) -> list[str]:
    """What in *cabinet* (``{key, from_date, to_date, phases}``) and its *posts* breaks
    a rule; empty when nothing does."""
    return _post_violations(cabinet, posts) + _phase_violations(cabinet)


def _count(posts: Iterable[dict[str, Any]], reason: str) -> int:
    return sum(1 for p in posts if reason in (p.get("corrected") or []))


def cabinet_row(cabinet: dict[str, Any], posts: list[dict[str, Any]]) -> dict[str, Any]:
    """What ``lawgraph verify cabinets`` shows of one cabinet."""
    phases = cabinet.get("phases") or []
    in_office = next((p for p in phases if p["kind"] == KIND_IN_OFFICE), None)
    overlapping = {p["seat"] for p in posts if p.get("overlaps_with")}
    return {
        "key": cabinet["key"],
        "from_date": cabinet["from_date"],
        "source": (cabinet.get("source") or {}).get("name"),
        "posts": len(posts),
        "seats": len(_by_seat(posts)),
        "gaps": len({g["seat"] for g in seat_gaps(posts)}),
        "overlaps": len(overlapping),
        "acting": sum(1 for p in posts if p.get("acting")),
        "corrected": _count(posts, CORRECTED_BY_SUCCESSOR)
        + _count(posts, CORRECTED_BY_PREDECESSOR),
        "clipped": _count(posts, CORRECTED_TO_CABINET),
        "double": sum(1 for p in posts if p.get("also_named")),
        "party": sum(1 for p in posts if p.get("party")),
        "no_party": sum(1 for p in posts if not p.get("party")),
        "own": sum(1 for p in posts if p.get("own")),
        "phases": len(phases),
        "demissionary_from": cabinet.get("demissionary_from"),
        "starts_agree": (
            None
            if in_office is None
            else in_office["from_date"] == cabinet["from_date"]
        ),
    }
