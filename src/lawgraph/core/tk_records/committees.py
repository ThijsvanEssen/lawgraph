"""Commissie: a committee and the seats on it."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final, Literal

from lawgraph.core.models import make_node_key
from lawgraph.core.slugs import claim_numbered
from lawgraph.core.time import iso_date
from lawgraph.core.tk_records._payload import (
    Payload,
    Record,
    dicts,
    first_text,
    id_of,
    is_deleted,
)

# Activiteit.Voortouwafkorting of an activity of the Kamer as a whole: a plenary debate, the
# votes, the regeling van werkzaamheden. Its Voortouwcommissie_Id names a Commissie record
# that has no name, because the plenary is no committee.
PLENARY_VOORTOUW = "TK"


def committee(payload: Payload) -> Record | None:
    """Node key and props for a Commissie record; ``None`` without an id or a name.

    The source has records with nothing but an id (the voortouw of every plenary
    activity is one). A record without a name is not written, so no id stands in for a
    name; once the source fills it in, the next run writes it.
    """
    external_id = id_of(payload)
    name = first_text(payload, "NaamNL", "Naam")
    if not external_id or not name:
        return None
    abbreviation = first_text(payload, "Afkorting")
    return make_node_key(external_id), {
        "external_id": external_id,
        "name": name,
        "abbreviation": abbreviation,
        "slug": make_node_key(abbreviation or name),
        "kind": committee_kind(name, first_text(payload, "Inhoudsopgave")),
        "started_on": iso_date(payload.get("DatumActief")),
        "ended_on": iso_date(payload.get("DatumInactief")),
        "display_name": name,
    }


# The kind of a committee, by its name, else by the group the Kamer lists it in
# (``Commissie.Inhoudsopgave``): an enquête or ondervraging before "Parlementaire".
CommitteeKind = Literal[
    "vast", "algemeen", "tijdelijk", "enquete", "delegatie", "overig"
]
COMMITTEE_OTHER: Final[CommitteeKind] = "overig"
_COMMITTEE_KINDS: tuple[tuple[CommitteeKind, re.Pattern[str]], ...] = (
    ("enquete", re.compile(r"(?:enqu[eê]te|ondervragings)commissie", re.IGNORECASE)),
    ("vast", re.compile(r"^vaste commissie\b", re.IGNORECASE)),
    ("algemeen", re.compile(r"^algemene commissie\b", re.IGNORECASE)),
    ("tijdelijk", re.compile(r"^(?:tijdelijke\b|themacommissie\b)", re.IGNORECASE)),
    (
        "delegatie",
        re.compile(
            r"^(?:contactgroep|ipc|interparlementaire)\b|assemblee|europol",
            re.IGNORECASE,
        ),
    ),
)
_COMMITTEE_GROUPS: dict[str, CommitteeKind] = {
    "Vaste commissies": "vast",
    "Algemene commissies": "algemeen",
    "Tijdelijke commissies": "tijdelijk",
    "Delegaties naar internationale vergaderingen": "delegatie",
}


def committee_kind(name: str, group: str | None) -> CommitteeKind:
    """``vast``, ``algemeen``, ``tijdelijk``, ``enquete``, ``delegatie`` or ``overig``."""
    for kind, pattern in _COMMITTEE_KINDS:
        if pattern.search(name):
            return kind
    return _COMMITTEE_GROUPS.get(group or "", COMMITTEE_OTHER)


def unique_committee_slugs(committees: list[dict[str, Any]]) -> None:
    """Give every committee in *committees* (their props) a slug of its own.

    Several committees share an abbreviation (``ez``, ``buhaos``): the one sitting now, else
    the one that ended last, keeps it; the others get the year they started (``ez-2010``),
    with a number behind it when that is taken too.
    """
    by_slug: dict[str, list[dict[str, Any]]] = {}
    for props in committees:
        by_slug.setdefault(props["slug"], []).append(props)
    taken = set(by_slug)
    for slug, group in by_slug.items():
        group.sort(
            key=lambda p: (
                p.get("ended_on") is None,
                p.get("ended_on") or "",
                p.get("started_on") or "",
                p["external_id"],
            ),
            reverse=True,
        )
        for props in group[1:]:
            year = (props.get("started_on") or props.get("ended_on") or "")[:4]
            base = f"{slug}-{year}" if year else slug
            props["slug"] = claim_numbered(base, taken)


@dataclass(frozen=True)
class CommitteeSeat:
    """One period a person held a seat on a commissie: from, to (inclusive, None while
    open), the role (``CommissieZetel…Persoon.Functie``, ``seat_role``: ``Lid``,
    ``Voorzitter``, ``OnderVz``, ``PlvLid``) and whether it was a substitute's seat
    (``CommissieZetelVervangerPersoon``)."""

    from_date: str | None
    to_date: str | None
    role: str | None = None
    substitute: bool = False


def seat_role(functie: str | None) -> str | None:
    """The ``Functie`` of a committee seat in one spelling: its words run together, each
    capitalised, without dots (``PlvLid``, as the Kamer writes it now, also for the
    ``Plv. lid`` of older seats; ``OnderVz``, ``Lid``)."""
    words = re.findall(r"[^\W_]+", functie or "")
    return "".join(w[0].upper() + w[1:] for w in words) or None


def committee_seats(payload: Payload) -> dict[str, list[CommitteeSeat]]:
    """``Persoon_Id`` -> every seat they held on this commissie, a member's
    (``CommissieZetelVastPersoon``) and a substitute's (``CommissieZetelVervangerPersoon``),
    one level below the seat, where the dates and the role live."""
    seats: dict[str, list[CommitteeSeat]] = {}
    for seat in dicts(payload.get("CommissieZetel")):
        for part, substitute in (
            ("CommissieZetelVastPersoon", False),
            ("CommissieZetelVervangerPersoon", True),
        ):
            for held in dicts(seat.get(part)):
                person_id = str(held.get("Persoon_Id") or "")
                if person_id and not is_deleted(held):
                    seats.setdefault(person_id, []).append(
                        CommitteeSeat(
                            iso_date(held.get("Van")),
                            iso_date(held.get("TotEnMet")),
                            seat_role(first_text(held, "Functie")),
                            substitute,
                        )
                    )
    return seats


def _seat_meta(seat: CommitteeSeat) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    if seat.from_date:
        meta["from_date"] = seat.from_date
    if seat.to_date:
        meta["to_date"] = seat.to_date
    if seat.role:
        meta["role"] = seat.role
    if seat.substitute:
        meta["substitute"] = True
    return meta


def representative_period(seats: list[CommitteeSeat]) -> dict[str, Any]:
    """Edge meta for the one seat that represents a membership, and every seat.

    An edge key is deterministic per (member, committee), so several seats collapse into
    one edge: an open-ended seat wins over a closed one, a member's over a substitute's,
    and among equals the latest one does. ``periods`` holds every seat, oldest first, when
    there is more than one or it has a role.
    """
    best = max(
        seats,
        key=lambda s: (
            s.to_date is None,
            not s.substitute,
            s.to_date or "",
            s.from_date or "",
        ),
    )
    meta = _seat_meta(best)
    if len(seats) > 1 or best.role:
        meta["periods"] = [
            _seat_meta(s)
            for s in sorted(seats, key=lambda s: (s.from_date or "", s.to_date or ""))
        ]
    return meta
