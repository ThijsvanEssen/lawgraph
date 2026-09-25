"""The phases of a cabinet: formatie, in functie, demissionair, dubbel demissionair, missionair.

A Rijksoverheid cabinet page gives dated facts (``Beëdiging kabinet: 2 juli 2024``,
``Ontslagaanvraag ingetrokken: 8 juni 1999``, ``Tweede Kamerverkiezingen: 15 mei 2002``) and
sentences that say a cabinet or some of its members resigned on a day. ``event_kind`` reads
from the label what the event does; ``cabinet_events`` gives every event to the cabinet in
office that day (the page of the next cabinet names the resignation of the one before it);
``cabinet_phases`` walks them:

- ``formatie``: from the earliest dated fact of the page's ``Kabinetsformatie`` block (the
  elections, or the resignation of the cabinet before) to the beëdiging;
- ``in_functie``: from the beëdiging;
- ``demissionair``: from the first resignation; a second one while demissionair (a party
  leaves a cabinet that already resigned) makes it ``dubbel_demissionair``;
- ``missionair``: a resignation withdrawn or refused (``Ontslagaanvraag ingetrokken``);
- ``null``: the elections held while the cabinet was in office, when the source names no
  resignation before them: from then on the cabinet was not ``in_functie`` as before, but
  the source does not give the day it resigned.

Every phase keeps the source's words as ``label``; they end where the next begins, the last
at the end of the cabinet (``None`` while it is in office).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from lawgraph.core.cabinets import cabinet_on

KIND_FORMATION = "formatie"
KIND_IN_OFFICE = "in_functie"
KIND_DEMISSIONARY = "demissionair"
KIND_DOUBLE_DEMISSIONARY = "dubbel_demissionair"
KIND_RESTORED = "missionair"
PHASE_KINDS = (
    KIND_FORMATION,
    KIND_IN_OFFICE,
    KIND_DEMISSIONARY,
    KIND_DOUBLE_DEMISSIONARY,
    KIND_RESTORED,
)

# What an event does, by its label (``event_kind``).
EVENT_SWORN_IN = "sworn_in"
EVENT_ELECTIONS = "elections"
EVENT_RESIGNED = "resigned"
EVENT_WITHDRAWN = "withdrawn"

_EVENTS: tuple[tuple[str, str], ...] = (
    (r"^beëdiging", EVENT_SWORN_IN),
    (r"verkiezing", EVENT_ELECTIONS),
    (r"^ontslagaanvraag (ingetrokken|geweigerd)", EVENT_WITHDRAWN),
    (r"^ontslagaanvraag|^terbeschikkingstelling", EVENT_RESIGNED),
)

BLOCK_FORMATION = "Kabinetsformatie"
_DEMISSIONARY = (KIND_DEMISSIONARY, KIND_DOUBLE_DEMISSIONARY)


def event_kind(label: str, *, sentence: bool = False) -> str | None:
    """What a dated fact with *label* does; a resignation sentence always resigns."""
    if sentence:
        return EVENT_RESIGNED
    plain = label.strip().lower()
    for pattern, kind in _EVENTS:
        if re.search(pattern, plain):
            return kind
    return None


def page_events(page: dict[str, Any], source: dict[str, Any]) -> list[dict[str, Any]]:
    """``{date, label, event, formation, source}`` of every dated fact and resignation
    sentence of a parsed page; ``formation`` for a fact of its formatie block."""
    events = [
        {
            "date": fact["date"],
            "label": fact["text"],
            "event": event_kind(fact["label"]),
            "formation": fact["block"] == BLOCK_FORMATION,
            "source": source,
        }
        for fact in page["facts"]
        if fact["date"]
    ]
    events += [
        {
            "date": said["date"],
            "label": said["label"],
            "event": EVENT_RESIGNED,
            "formation": False,
            "source": source,
        }
        for said in page["resignations"]
        if said["date"]
    ]
    return events


def formation_start(
    events: Iterable[dict[str, Any]], sworn_in: str
) -> dict[str, Any] | None:
    """The earliest fact of a page's formatie block before its beëdiging."""
    before = [e for e in events if e["formation"] and e["date"] < sworn_in]
    return min(before, key=lambda e: e["date"]) if before else None


def cabinet_events(
    events: Iterable[dict[str, Any]], cabinets: list[dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    """Cabinet key -> the events in its term, by the day: a resignation or elections on
    the page of the next cabinet belong to the one in office then. A beëdiging and the
    facts that open a formatie do not change the cabinet in office."""
    found: dict[str, list[dict[str, Any]]] = {c["key"]: [] for c in cabinets}
    seen: set[tuple[str, str, str | None]] = set()
    for event in sorted(events, key=lambda e: e["date"]):
        if event["event"] == EVENT_SWORN_IN:
            continue
        key = cabinet_on(event["date"], cabinets)
        if key is None:
            continue
        cabinet = next(c for c in cabinets if c["key"] == key)
        if event["date"] <= cabinet["from_date"]:
            continue
        mark = (key, event["date"], event["event"])
        if mark in seen:
            continue
        seen.add(mark)
        found[key].append(event)
    return found


def _next_kind(current: str | None, event: str | None) -> str | None | bool:
    """The kind of the phase an event opens, or ``False`` when it opens none."""
    if event == EVENT_RESIGNED:
        if current == KIND_DEMISSIONARY:
            return KIND_DOUBLE_DEMISSIONARY
        return False if current in _DEMISSIONARY else KIND_DEMISSIONARY
    if event == EVENT_WITHDRAWN:
        return KIND_RESTORED if current in _DEMISSIONARY else False
    if event == EVENT_ELECTIONS:
        return None if current in (KIND_IN_OFFICE, KIND_RESTORED) else False
    return False


def cabinet_phases(
    cabinet: dict[str, Any],
    sworn_in: dict[str, Any],
    formation: dict[str, Any] | None,
    events: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """The phases of *cabinet* (``{from_date, to_date}``): *sworn_in* the event that opens
    its term, *formation* the one that opened its formatie, *events* those of its term."""
    phases: list[dict[str, Any]] = []
    if formation:
        phases.append(_phase(KIND_FORMATION, formation))
    phases.append(_phase(KIND_IN_OFFICE, {**sworn_in, "date": cabinet["from_date"]}))
    current: str | None = KIND_IN_OFFICE
    for event in sorted(events, key=lambda e: e["date"]):
        if cabinet["to_date"] and event["date"] >= cabinet["to_date"]:
            break
        kind = _next_kind(current, event["event"])
        if kind is False:
            continue
        phases.append(_phase(kind, event))  # type: ignore[arg-type]
        current = kind  # type: ignore[assignment]
    for phase, after in zip(phases, phases[1:], strict=False):
        phase["to_date"] = after["from_date"]
    phases[-1]["to_date"] = cabinet["to_date"]
    return phases


def _phase(kind: str | None, event: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": kind,
        "from_date": event["date"],
        "to_date": None,
        "label": event["label"],
        "source": event["source"],
    }


def demissionary_from(phases: Iterable[dict[str, Any]]) -> str | None:
    """The start of the first ``demissionair`` phase."""
    return next(
        (p["from_date"] for p in phases if p["kind"] == KIND_DEMISSIONARY), None
    )
