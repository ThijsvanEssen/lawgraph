"""Persoon: a member, and the name a vote or signature gives a person."""

from __future__ import annotations

from typing import Any

from lawgraph.core.models import make_node_key
from lawgraph.core.time import iso_date
from lawgraph.core.tk_records._payload import (
    Payload,
    Record,
    first_text,
    id_of,
)
from lawgraph.core.xml import collapse_ws


def member(payload: Payload) -> Record | None:
    """Node key and props for a Persoon record; ``None`` without an id.

    Party affiliation is not read here: it follows from the
    FractieZetelPersoon timeline, which is the one source that dates it.
    """
    external_id = id_of(payload)
    if not external_id:
        return None
    surname = f"{payload.get('Tussenvoegsel') or ''} {payload.get('Achternaam') or ''}"
    # a member of old the Kamer knows by initials alone: ``W.B. Buma`` (1807-1848)
    initials = _dotted_initials(first_text(payload, "Initialen"))
    first = payload.get("Voornamen") or initials
    full_name = collapse_ws(f"{first} {surname}")
    # the name a person goes by: ``Ard van der Steur``, not ``Gerard Adriaan van der Steur``
    called = payload.get("Roepnaam") or first
    name = collapse_ws(f"{called} {surname}")
    props: dict[str, Any] = {
        "external_id": external_id,
        "full_name": full_name or None,
        # what another source knows a person by (``core.government.match_holder``)
        "family_name": first_text(payload, "Achternaam") or None,
        "name_prefix": first_text(payload, "Tussenvoegsel") or None,
        "initials": first_text(payload, "Initialen") or None,
        "birth_date": iso_date(payload.get("Geboortedatum")),
        "death_date": iso_date(payload.get("Overlijdensdatum")),
        # Persoon.Nummer: what a namesake's slug ends in when the year does not tell
        "number": str(payload["Nummer"]) if payload.get("Nummer") else None,
    }
    if name:
        # a Persoon the Kamer gives no name (a record it withholds) keeps the name its
        # roll-call votes and signatures gave (``_tk_members.name_nameless_members``)
        props["name"] = props["display_name"] = name
    return make_node_key(external_id), props


def _dotted_initials(initials: str) -> str:
    """``W.B.`` of ``WB``: the Kamer writes the initials of members of old without dots."""
    if not initials or "." in initials:
        return initials
    return "".join(f"{letter}." for letter in initials if letter.isalpha())


def display_person_name(actor_name: str | None) -> str | None:
    """ "J.N.J. Nobel" of "Nobel, J.N.J.", as a Stemming or a DocumentActor names a person."""
    if not actor_name:
        return None
    family, _, initials = actor_name.partition(",")
    return collapse_ws(f"{initials.strip()} {family.strip()}") or None
