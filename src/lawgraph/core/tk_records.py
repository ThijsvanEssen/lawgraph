"""Readers for Tweede Kamer OData records: one payload in, node props out.

The field names read here (``Voortouwcommissie_Id``, ``Agendapunt``,
``FractieGrootte``) are the TK API's own. Everything these functions return is
graph vocabulary: a node key plus a props mapping, ready to wrap in a ``Node``.

Nothing in this module touches the database, so every reader is unit-testable
against a single recorded payload.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any

from lawgraph.config.constants import SOURCE_TK
from lawgraph.core.dossier_stages import dossier_display_name
from lawgraph.core.models import make_node_key
from lawgraph.core.time import iso_date

Payload = dict[str, Any]
Record = tuple[str, dict[str, Any]]

TK_ACTIVITY_URL = "https://www.tweedekamer.nl/vergaderingen/details?id={id}"
TK_DOCUMENT_URL = "https://www.tweedekamer.nl/kamerstukken/detail?id={id}"

# Toezegging.Status -> the status we store. The source distinguishes a
# commitment that was settled from one that was explicitly not kept.
COMMITMENT_STATUS = {
    "Openstaand": "open",
    "Afgedaan": "done",
    "Nagekomen": "done",
    "Niet nagekomen": "unfulfilled",
    # seen in the real data: were mapped to "open" because the map did not know them
    "Deels Afgedaan": "partly_done",
    "Vervallen": "lapsed",
}

# Stemming.Soort values that mean the vote was cast in favour / against; any
# other value ("Onthouden", "Niet deelgenomen") is kept as the source wrote it.
VOTE_FOR = "Voor"
VOTE_AGAINST = "Tegen"

VOTE_KIND_MEMBER = "member"
VOTE_KIND_FACTION = "faction"

_COMMITMENT_TEXT_FIELDS = ("Tekst", "TekstAlgemeen", "TekstBrief")


def _dicts(value: Any) -> Iterator[Payload]:
    """Yield the dicts in *value*, which TK gives as a list, a dict or null."""
    if isinstance(value, dict):
        yield value
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                yield item


def _text(payload: Payload, *fields: str) -> str:
    """First non-empty string among *fields*."""
    for field in fields:
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _external_id(payload: Payload) -> str:
    return str(payload.get("Id") or "")


def _distinct(values: Iterable[str]) -> list[str]:
    """Non-empty values, deduplicated, in first-seen order."""
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


# ── Zaak (Case) references ───────────────────────────────────────────────────


def case_ids(cases: Iterable[Payload]) -> list[str]:
    """Zaak GUIDs of the given Zaak records."""
    return _distinct(str(record.get("Id") or "") for record in cases)


def dossier_label(number: Any, suffix: Any) -> str:
    """``37020-XV`` for Nummer 37020 with Toevoeging XV, ``37020`` without one.

    ``make_node_key`` of the label is the key of the dossier node.
    """
    number_str = str(number or "")
    return f"{number_str}-{suffix}" if number_str and suffix else number_str


def _dossier_label(dossier: Payload) -> str:
    return dossier_label(dossier.get("Nummer"), dossier.get("Toevoeging"))


def dossier_numbers(cases: Iterable[Payload]) -> list[str]:
    """Kamerstukdossier labels (``37020``, ``37020-XV``) of the given Zaak records."""
    return _distinct(
        _dossier_label(dossier)
        for record in cases
        for dossier in _dicts(record.get("Kamerstukdossier"))
    )


def case_kinds(cases: Iterable[Payload]) -> list[str]:
    """Distinct ``Zaak.Soort`` values (Wetgeving, Motie, Amendement, …)."""
    return _distinct(str(record.get("Soort") or "") for record in cases)


def case_kinds_by_dossier(cases: Iterable[Payload]) -> dict[str, list[str]]:
    """Distinct ``Zaak.Soort`` values (Wetgeving, Motie, …) per Kamerstukdossier label.

    Each dossier gets the kinds of its own cases only: one agenda (a day of votes) holds
    the cases of many dossiers.
    """
    pairs = [
        (_dossier_label(dossier), str(record.get("Soort") or ""))
        for record in cases
        for dossier in _dicts(record.get("Kamerstukdossier"))
    ]
    numbers = _distinct(number for number, _ in pairs)
    return {
        number: _distinct(kind for n, kind in pairs if n == number)
        for number in numbers
    }


def agenda_cases(payload: Payload) -> list[Payload]:
    """The Zaak records on every Agendapunt of an Activiteit or Besluit."""
    return [
        record
        for item in _dicts(payload.get("Agendapunt"))
        for record in _dicts(item.get("Zaak"))
    ]


# ── Commissie (Committee) ────────────────────────────────────────────────────


def committee(payload: Payload) -> Record | None:
    """Node key and props for a Commissie record."""
    external_id = _external_id(payload)
    if not external_id:
        return None
    name = _text(payload, "NaamNL", "Naam") or external_id
    abbreviation = _text(payload, "Afkorting")
    return make_node_key(external_id), {
        "external_id": external_id,
        "name": name,
        "abbreviation": abbreviation,
        "slug": make_node_key(abbreviation or name),
        "display_name": name,
    }


def committee_seats(payload: Payload) -> dict[str, list[tuple[str | None, str | None]]]:
    """``Persoon_Id`` -> the [from, to] periods they held a seat on this commissie.

    The dates live on ``CommissieZetelVastPersoon``, one level below the seat.
    """
    periods: dict[str, list[tuple[str | None, str | None]]] = {}
    for seat in _dicts(payload.get("CommissieZetel")):
        for held in _dicts(seat.get("CommissieZetelVastPersoon")):
            person_id = str(held.get("Persoon_Id") or "")
            if person_id:
                periods.setdefault(person_id, []).append(
                    (iso_date(held.get("Van")), iso_date(held.get("TotEnMet")))
                )
    return periods


def representative_period(
    periods: list[tuple[str | None, str | None]],
) -> dict[str, str]:
    """Edge meta for the one period that represents a membership.

    An edge key is deterministic per (member, committee), so several periods
    collapse into one edge: an open-ended period wins over a closed one, and
    among equals the latest one does.
    """
    open_periods = [(start, end) for start, end in periods if end is None]
    if open_periods:
        start = max((s for s, _ in open_periods if s), default=None)
        end = None
    else:
        start, end = max(periods, key=lambda p: p[1] or "")
    meta: dict[str, str] = {}
    if start:
        meta["from_date"] = start
    if end:
        meta["to_date"] = end
    return meta


# ── Persoon (Member) ─────────────────────────────────────────────────────────


def member(payload: Payload) -> Record | None:
    """Node key and props for a Persoon record.

    Party affiliation is not read here: it follows from the
    FractieZetelPersoon timeline, which is the one source that dates it.
    """
    external_id = _external_id(payload)
    if not external_id:
        return None
    name = " ".join(
        f"{payload.get('Voornamen') or ''} {payload.get('Tussenvoegsel') or ''} "
        f"{payload.get('Achternaam') or ''}".split()
    )
    return make_node_key(external_id), {
        "external_id": external_id,
        "name": name,
        "display_name": name,
    }


def seat_holding(payload: Payload) -> tuple[str, str, dict[str, Any]] | None:
    """``(Persoon_Id, Fractie_Id, period)`` for a FractieZetelPersoon record."""
    person_id = str(payload.get("Persoon_Id") or "")
    seat = next(_dicts(payload.get("FractieZetel")), {})
    faction_id = str(seat.get("Fractie_Id") or "")
    if not person_id or not faction_id:
        return None
    return (
        person_id,
        faction_id,
        {
            "from_date": iso_date(payload.get("Van")),
            "to_date": iso_date(payload.get("TotEnMet")),
            "role": payload.get("Functie") or None,
        },
    )


# ── Fractie (Faction) ────────────────────────────────────────────────────────


def faction_label(payload: Payload) -> str:
    """The name a Fractie is keyed by: its abbreviation, else its full name."""
    return _text(payload, "Afkorting") or _text(payload, "NaamNL")


def faction_aliases(payload: Payload, vote_labels: Iterable[str]) -> list[str]:
    """Every spelling of this fractie that other TK endpoints use.

    ``Fractie.Afkorting`` is sometimes the full party name while
    ``Stemming.ActorFractie`` uses the short form, so the alias set is what
    joins the two. An auto-acronym is accepted only when a vote actually uses
    it; unvalidated guesses would merge distinct parties.
    """
    abbreviation = _text(payload, "Afkorting")
    name = _text(payload, "NaamNL")
    label = abbreviation or name
    labels = set(vote_labels)
    aliases = {value for value in (abbreviation, name) if value}
    acronym = "".join(w[0] for w in name.split() if w and w[0].isalpha()).upper()
    if len(acronym) >= 2 and acronym in labels:
        aliases.add(acronym)
    aliases.update(
        spelling
        for spelling in labels
        if make_node_key(spelling) == make_node_key(label)
    )
    return sorted(aliases)


def faction(payload: Payload, aliases: list[str]) -> Record | None:
    """Node key and props for a Fractie record."""
    external_id = _external_id(payload)
    label = faction_label(payload)
    if not external_id or not label:
        return None
    abbreviation = _text(payload, "Afkorting")
    name = _text(payload, "NaamNL")
    return make_node_key(label), {
        "external_id": external_id,
        "name": name or abbreviation,
        "abbreviation": abbreviation or None,
        "aliases": aliases,
        "active_from": iso_date(payload.get("DatumActief")),
        "active_until": iso_date(payload.get("DatumInactief")),
        "seats": payload.get("AantalZetels"),
        "active": payload.get("DatumInactief") is None,
        "display_name": abbreviation or name,
    }


def faction_is_current(payload: Payload) -> tuple[int, str]:
    """Sort key that prefers a seated Fractie, then the most recently changed.

    TK recycles afkortingen — a party that dissolves and reforms gets a fresh
    record with the same one — and both records key to the same node.
    """
    return (
        1 if payload.get("DatumInactief") is None else 0,
        str(payload.get("GewijzigdOp") or ""),
    )


# ── Kamerstukdossier (Dossier) ───────────────────────────────────────────────


def dossier(payload: Payload) -> tuple[str, str, dict[str, Any]] | None:
    """``(node key, dossier number label, props)`` for a Kamerstukdossier."""
    external_id = _external_id(payload)
    number = payload.get("Nummer")
    if not external_id or number is None:
        return None

    number_str = str(number)
    suffix = payload.get("Toevoeging") or ""
    label = dossier_label(number_str, suffix)
    # A dossier with neither Titel nor Citeertitel keeps title None, so the
    # backfill can take one from a voorstel-van-wet document instead of
    # storing a title that only looks valid.
    title = payload.get("Titel") or payload.get("Citeertitel") or None

    # The record says nothing about how far the dossier got: ``Afgesloten`` is false on
    # every dossier, also on those whose law was published years ago. When it was opened
    # and whether and how it ended are derived from the graph (the stage backfill and
    # ``semantic tk-dossier-outcomes``), so they are not written here, where a run would
    # blank them.
    props: dict[str, Any] = {
        "external_id": external_id,
        "number": number_str,
        "suffix": suffix,
        "label": label,
        "title": title,
        "title_source": "dossier" if title else None,
        "display_name": dossier_display_name(number_str, suffix, title or ""),
    }

    return make_node_key(label), label, props


# ── Activiteit (Activity) ────────────────────────────────────────────────────


def activity(payload: Payload) -> Record | None:
    """Node key and props for an Activiteit record."""
    external_id = _external_id(payload)
    if not external_id:
        return None

    cases = agenda_cases(payload)
    date = iso_date(payload.get("Datum"))
    description = payload.get("Omschrijving") or ""
    kind = payload.get("Soort") or ""
    voortouw = payload.get("Voortouwcommissie_Id")

    return make_node_key(external_id), {
        "external_id": external_id,
        "date": date,
        "agenda_title": description,
        "kind": kind,
        # Absent for a plenary activity, which has no lead committee.
        "committee_id": str(voortouw) if voortouw else None,
        "case_ids": case_ids(cases),
        "dossier_numbers": dossier_numbers(cases),
        "case_kinds_by_dossier": case_kinds_by_dossier(cases),
        "tk_url": TK_ACTIVITY_URL.format(id=external_id),
        "display_name": f"{date or '?'} — {description or kind}",
        "number": str(payload.get("Nummer") or ""),
    }


# ── Toezegging (Commitment) ──────────────────────────────────────────────────


def commitment(payload: Payload) -> Record | None:
    """Node key and props for a Toezegging record."""
    external_id = _external_id(payload)
    if not external_id:
        return None

    text = _text(payload, *_COMMITMENT_TEXT_FIELDS)
    raw_status = payload.get("Status") or "Openstaand"
    return make_node_key(external_id), {
        "external_id": external_id,
        "text": text,
        "minister_name": _text(payload, "Naam", "MinisterNaam"),
        "minister_role": _text(payload, "Functie", "MinisterTitel"),
        "made_on": iso_date(payload.get("Aanmaakdatum")),
        "expected_resolution": iso_date(payload.get("DatumNakoming")),
        "status": COMMITMENT_STATUS.get(raw_status, "open"),
        "activity_number": str(payload.get("ActiviteitNummer") or ""),
        "display_name": (text[:80] + "…") if len(text) > 80 else text,
    }


def unknown_commitment_statuses(payloads: Iterable[Payload]) -> set[str]:
    """Toezegging.Status values the status map does not cover."""
    return {
        str(payload.get("Status"))
        for payload in payloads
        if payload.get("Status") and payload.get("Status") not in COMMITMENT_STATUS
    }


# ── Document (Kamerstuk) ─────────────────────────────────────────────────────


def document_actors(payload: Payload) -> list[dict[str, Any]]:
    """Signatories of a Document, from the DocumentActor expansion."""
    actors: list[dict[str, Any]] = []
    for actor in _dicts(payload.get("DocumentActor")):
        person_id = str(actor.get("Persoon_Id") or "") or None
        name = actor.get("ActorNaam") or ""
        if not (person_id or name):
            continue
        actors.append(
            {
                "person_id": person_id,
                "faction_id": str(actor.get("Fractie_Id") or "") or None,
                "name": name,
                "faction": actor.get("ActorFractie") or "",
                "role": actor.get("Relatie") or "",
            }
        )
    return actors


def document(payload: Payload) -> Record | None:
    """Node key and props for a Document (Kamerstuk) record.

    A Document carries no dossier number of its own; it reaches dossiers
    through Zaak → Kamerstukdossier, and one document may reach several.
    """
    external_id = _external_id(payload)
    if not external_id:
        return None

    cases = list(_dicts(payload.get("Zaak")))
    dossiers = dossier_numbers(cases)
    kind = payload.get("Soort") or ""
    title = payload.get("Titel") or payload.get("Onderwerp") or kind
    sequence = payload.get("Volgnummer")  # -1 marks a non-Kamerstuk

    return make_node_key(external_id), {
        "source": SOURCE_TK,
        "external_id": external_id,
        "raw": payload,
        "dossier_numbers": dossiers,
        "case_ids": case_ids(cases),
        "case_kinds": case_kinds(cases),
        "sequence": sequence if (sequence or 0) > 0 else None,
        "kind": kind,
        "title": title,
        "subject": payload.get("Onderwerp") or "",
        "date": iso_date(payload.get("Datum") or payload.get("DatumRegistratie")),
        "session_year": payload.get("Vergaderjaar") or "",
        "tk_url": TK_DOCUMENT_URL.format(id=external_id),
        "display_name": document_display_name(
            dossiers[0] if dossiers else None, sequence, kind, title
        ),
        "actors": document_actors(payload),
    }


def document_display_name(
    dossier_number: str | None,
    sequence: Any,
    kind: str,
    title: str,
) -> str:
    """``Kamerstuk 29684, nr. 7 — Motie: <title>``."""
    if dossier_number and (sequence or 0) > 0:
        name = f"Kamerstuk {dossier_number}, nr. {sequence}"
    elif dossier_number:
        name = f"Kamerstuk {dossier_number}"
    else:
        name = kind or "Document"
    if kind:
        name += f" — {kind}"
    if title and title != kind:
        name += f": {title[:120]}"
    return name


# ── Stemming / Besluit (Decision and its votes) ──────────────────────────────


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


def vote(payload: Payload) -> VoteCast | None:
    decision_id = str(payload.get("Besluit_Id") or "")
    if not decision_id:
        return None
    faction_id = str(payload.get("Fractie_Id") or "")
    return VoteCast(
        decision_id=sys.intern(decision_id),
        choice=sys.intern(str(payload.get("Soort") or "")),
        seats=payload.get("FractieGrootte") or 0,
        person_id=str(payload.get("Persoon_Id") or "") or None,
        faction_id=sys.intern(faction_id) if faction_id else None,
        faction_label=sys.intern((payload.get("ActorFractie") or "").strip()),
        changed_at=payload.get("GewijzigdOp"),
    )


def decision(decision_id: str, decision: Payload, votes: list[VoteCast]) -> Record:
    """Node key and props for one Besluit and the votes cast on it.

    The tally is stored so a list row costs no edge traversal; who voted how
    is on the VOTED edges.
    """
    own = list(_dicts(decision.get("Zaak")))
    cases = own + agenda_cases(decision)
    agenda_item = next(_dicts(decision.get("Agendapunt")), {})
    activity = next(_dicts(agenda_item.get("Activiteit")), {})
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

    tally: dict[str, int] = {}
    voters: dict[str, int] = {}
    for cast in votes:
        choice = cast.choice
        tally[choice] = tally.get(choice, 0) + int(cast.seats or 0)
        voters[choice] = voters.get(choice, 0) + 1

    roll_call = any(cast.person_id for cast in votes)
    if roll_call:
        # In a roll-call each row is one member, so FractieGrootte would count
        # the whole faction for every one of them.
        tally = dict(voters)

    return make_node_key("decision", decision_id), {
        "decision_id": decision_id,
        "agenda_item_id": str(decision.get("Agendapunt_Id") or ""),
        # The day of the vote; a row's GewijzigdOp is when it was last edited.
        "date": iso_date(activity.get("Datum"))
        or (iso_date(votes[0].changed_at) if votes else None),
        "subject": subject,
        "agenda_item_subject": agenda_item.get("Onderwerp") or "",
        "decision_text": decision_text,
        "decision_order": order,
        "meeting_kind": agenda_item.get("Vergadering_Soort") or "",
        "case_ids": case_ids(cases),
        "primary_case_id": str(primary.get("Id") or "") if primary else None,
        "primary_case_kind": (primary.get("Soort") or None) if primary else None,
        "dossier_numbers": dossier_numbers(cases),
        "vote_kind": VOTE_KIND_MEMBER if roll_call else VOTE_KIND_FACTION,
        "tally": tally,
        "voters": voters,
        "passed": decision_passed(decision, tally),
        "display_name": decision_display_name(primary, order, len(listed), subject),
    }


def decision_passed(decision: Payload, tally: dict[str, int]) -> bool:
    """Whether the decision carried: the source says so, or the tally does."""
    kind = (
        decision.get("BesluitSoort") or decision.get("StemmingsSoort") or ""
    ).lower()
    if "aangenomen" in kind:
        return True
    if "verworpen" in kind:
        return False
    return tally.get(VOTE_FOR, 0) > tally.get(VOTE_AGAINST, 0)


def decision_display_name(
    primary: Payload | None,
    order: int | None,
    case_count: int,
    subject: str,
) -> str:
    """``Motie 2024Z17945 — <subject>``, distinct per sibling on an Agendapunt.

    The outcome is left out: the frontend renders it as a badge.
    """
    if primary and primary.get("Nummer"):
        head = f"{primary.get('Soort') or 'Stemming'} {primary['Nummer']}"
    elif order is not None and case_count:
        head = f"Stemming {order}/{case_count}"
    else:
        head = "Stemming"
    return f"{head} — {subject}" if subject else head


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
