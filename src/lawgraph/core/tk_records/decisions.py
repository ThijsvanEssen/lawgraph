"""Besluit and Stemming: a decision and the votes cast on it."""

from __future__ import annotations

import sys
from collections import Counter
from dataclasses import dataclass
from typing import Any, Final, Literal

from lawgraph.core.models import make_node_key
from lawgraph.core.time import iso_date
from lawgraph.core.tk_records._payload import (
    Payload,
    Record,
    dicts,
)
from lawgraph.core.tk_records.cases import agenda_cases, case_ids, dossier_numbers
from lawgraph.core.tk_records.kinds import starts_with_kind
from lawgraph.core.votes import ADOPTED, REJECTED, VOTE_AGAINST, VOTE_FOR

# Who the votes of a decision come from: the members (a roll call), else the factions.
VoteKind = Literal["member", "faction"]
VOTE_KIND_MEMBER: Final[VoteKind] = "member"
VOTE_KIND_FACTION: Final[VoteKind] = "faction"


@dataclass(frozen=True, slots=True)
class VoteCast:
    """One Stemming row: who voted on which Besluit, how, and with what weight.

    ``person_id`` is set on a roll-call vote and absent otherwise, which is
    what decides whether the VOTED edge starts at a member or at a faction.

    Every cast of a run is kept until the VOTED edges are written (190K for two years), so
    this is a slotted object with its repeating strings interned, not a dict: about a
    fifth of the memory.
    """

    decision_id: str
    choice: str
    seats: int
    person_id: str | None
    faction_id: str | None
    faction_label: str
    changed_at: str | None
    actor_name: str | None = None  # "Nobel, J.N.J.": who voted, as the row names them
    record_id: str | None = None  # the Stemming ``Id``, which its VOTED edge keeps


def decision_key(decision_id: str) -> str:
    """The node key of the decision on the Besluit *decision_id* (see ``decision``)."""
    return make_node_key("decision", decision_id)


def vote(payload: Payload) -> VoteCast | None:
    decision_id = str(payload.get("Besluit_Id") or "")
    if not decision_id:
        return None
    faction_id = str(payload.get("Fractie_Id") or "")
    person_id = str(payload.get("Persoon_Id") or "") or None
    return VoteCast(
        decision_id=sys.intern(decision_id),
        choice=sys.intern(str(payload.get("Soort") or "")),
        # a row of a roll-call is one member, whose FractieGrootte is that of the faction
        seats=1 if person_id else payload.get("FractieGrootte") or 0,
        person_id=person_id,
        faction_id=sys.intern(faction_id) if faction_id else None,
        faction_label=sys.intern((payload.get("ActorFractie") or "").strip()),
        changed_at=payload.get("GewijzigdOp"),
        actor_name=(payload.get("ActorNaam") or "").strip() or None
        if person_id
        else None,
        record_id=str(payload.get("Id") or "") or None,
    )


def is_roll_call(votes: list[VoteCast]) -> bool:
    """A roll call names every member: each row has a Persoon_Id. A faction vote in which
    a few members voted apart from their faction has rows of both kinds, and is none."""
    return bool(votes) and all(cast.person_id for cast in votes)


def seats_of(votes: list[VoteCast]) -> list[int]:
    """The seats each row of a decision weighs, in the order of *votes*: a member one; a
    faction its FractieGrootte without its members who voted apart in a row of their own
    (their rows give the size of the faction too)."""
    apart = Counter(cast.faction_id for cast in votes if cast.person_id)
    return [
        1
        if cast.person_id
        else max(int(cast.seats or 0) - apart.get(cast.faction_id, 0), 0)
        for cast in votes
    ]


def decision(decision_id: str, decision: Payload, votes: list[VoteCast]) -> Record:
    """Node key and props for one Besluit and the votes cast on it.

    The tally is stored so a list row costs no edge traversal; who voted how
    is on the VOTED edges.
    """
    own = list(dicts(decision.get("Zaak")))
    cases = own + agenda_cases(decision)
    agenda_item = next(dicts(decision.get("Agendapunt")), {})
    activity = next(dicts(agenda_item.get("Activiteit")), {})
    decision_text = decision.get("BesluitTekst") or ""

    # The Besluit's own Zaak is the case it decided: what tells the vote on a bill from
    # the votes on its amendments, and eighteen moties on one Agendapunt apart. Without
    # it only an Agendapunt of one case says which. AgendapuntZaakBesluitVolgorde is the
    # place of the Besluit on the Agendapunt, not of its Zaak in the list.
    order = _int_or_none(decision.get("AgendapuntZaakBesluitVolgorde"))
    listed = agenda_cases(decision)
    primary = own[0] if own else (listed[0] if len(listed) == 1 else None)

    # Prefer the per-motie subject over the agenda-item headline it shares with
    # its siblings. Zaak.Titel is deliberately not used: on a motie it carries
    # the parent dossier's umbrella title.
    subject = (
        (primary or {}).get("Onderwerp")
        or agenda_item.get("Onderwerp")
        or decision_text
        or f"Besluit {decision_id[:8]}"
    )

    # The rows of a decision come in no fixed order: in that of their ids, the first vote
    # (whose date stands in for a missing one) is the same on every run.
    votes = sorted(votes, key=lambda cast: (cast.record_id or "", cast.person_id or ""))
    tally: dict[str, int] = {}
    voters: dict[str, int] = {}
    for cast, seats in zip(votes, seats_of(votes), strict=True):
        choice = cast.choice
        tally[choice] = tally.get(choice, 0) + seats
        voters[choice] = voters.get(choice, 0) + 1
    roll_call = is_roll_call(votes)

    tally, voters = _in_vote_order(tally), _in_vote_order(voters)
    return decision_key(decision_id), {
        "decision_id": decision_id,
        "agenda_item_id": str(decision.get("Agendapunt_Id") or ""),
        # the activity of its agenda item: the meeting it was taken in (MADE_IN)
        "activity_id": str(activity.get("Id") or "") or None,
        # The day of the vote; a row's GewijzigdOp is when it was last edited.
        "date": iso_date(activity.get("Datum"))
        or (iso_date(votes[0].changed_at) if votes else None),
        "subject": subject,
        "agenda_item_subject": agenda_item.get("Onderwerp") or "",
        "decision_text": decision_text,
        "decision_kind": decision.get("BesluitSoort") or None,
        "decision_order": order,
        "meeting_kind": agenda_item.get("Vergadering_Soort") or "",
        "case_ids": case_ids(cases),
        "primary_case_id": str(primary.get("Id") or "") if primary else None,
        "primary_case_kind": (primary.get("Soort") or None) if primary else None,
        "kind": decision_kind(primary, listed),
        "dossier_numbers": dossier_numbers(cases),
        "vote_kind": (VOTE_KIND_MEMBER if roll_call else VOTE_KIND_FACTION)
        if votes
        else None,
        "tally": tally,
        "voters": voters,
        "passed": decision_passed(decision, tally),
        "display_name": decision_display_name(primary, order, len(listed), subject),
    }


def _in_vote_order(counts: dict[str, int]) -> dict[str, int]:
    """*counts* per choice as a tally is read: for, against, then the others in alphabetical
    order (``Niet deelgenomen``)."""
    order: dict[str, int] = {VOTE_FOR: 0, VOTE_AGAINST: 1}
    return dict(
        sorted(counts.items(), key=lambda item: (order.get(item[0], 2), item[0]))
    )


def decision_kind(primary: Payload | None, listed: list[Payload]) -> str | None:
    """What was decided on: the ``Zaak.Soort`` of the case decided (``Motie``,
    ``Amendement``, ``Wetgeving``, ...), as the Kamer writes it.

    Without a primary case, the cases on the Agendapunt answer when they are all of one
    Soort: an Agendapunt of moties alone decides a motie, whichever it is. None otherwise.
    """
    cases = [primary] if primary else listed
    kinds = {case.get("Soort") or None for case in cases}
    return kinds.pop() if len(kinds) == 1 else None


def decision_passed(decision: Payload, tally: dict[str, int]) -> bool | None:
    """Whether the decision carried: the source says so (``Stemmen - aangenomen``,
    ``Stemmen - zonder stemming aannemen``, ``Stemmen - verworpen``), or the tally of its
    votes does; None for a decision that is no vote (``Stemmen - uitstellen``)."""
    kind = (
        decision.get("BesluitSoort") or decision.get("StemmingsSoort") or ""
    ).lower()
    if ADOPTED in kind or "aannemen" in kind:
        return True
    if REJECTED in kind:
        return False
    if not tally:
        return None
    return tally.get(VOTE_FOR, 0) > tally.get(VOTE_AGAINST, 0)


def decision_display_name(
    primary: Payload | None,
    order: int | None,
    case_count: int,
    subject: str,
) -> str:
    """``Motie 2024Z17945: <subject>``, or the subject alone when it names its kind
    ("Motie van de leden …"); distinct per sibling on an Agendapunt. No dash: it is a
    heading.

    The outcome is left out: the frontend renders it as a badge.
    """
    kind = str((primary or {}).get("Soort") or "")
    if subject and starts_with_kind(subject, kind):
        return subject
    if primary and primary.get("Nummer"):
        head = f"{kind or 'Stemming'} {primary['Nummer']}"
    elif order is not None and case_count:
        head = f"Stemming {order}/{case_count}"
    else:
        head = "Stemming"
    return f"{head}: {subject}" if subject else head


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except TypeError, ValueError:
        return None
