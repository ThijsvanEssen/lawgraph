"""Fractie: a faction, one node for every record of it."""

from __future__ import annotations

from collections.abc import Iterable

from lawgraph.core.models import make_node_key
from lawgraph.core.time import iso_date
from lawgraph.core.tk_records._payload import (
    Payload,
    Record,
    first_text,
    id_of,
)


def faction_label(payload: Payload) -> str:
    """The name a Fractie is keyed by: its abbreviation, else its full name."""
    return first_text(payload, "Afkorting") or first_text(payload, "NaamNL")


def _acronym(name: str) -> str:
    """``NSC`` of ``Nieuw Sociaal Contract``: the first letter of every word."""
    return "".join(w[0] for w in name.split() if w and w[0].isalpha()).upper()


def faction_aliases(payload: Payload, vote_labels: Iterable[str]) -> list[str]:
    """Every name of this fractie: its abbreviation, its name and the names its own vote
    rows give it (*vote_labels*, ``Stemming.ActorFractie`` of the rows whose
    ``Fractie_Id`` is one of its records).

    ``Fractie.Afkorting`` is sometimes the full party name while its votes use the short
    form (``NSC``), so the alias set is what joins the two.
    """
    abbreviation = first_text(payload, "Afkorting")
    name = first_text(payload, "NaamNL")
    return sorted({abbreviation, name, *vote_labels} - {""})


def short_name(payload: Payload, aliases: Iterable[str]) -> str:
    """The abbreviation of a fractie: ``Afkorting``; where the Kamer gives the full name
    there (``Nieuw Sociaal Contract``), the acronym of it its votes use (``NSC``)."""
    abbreviation = first_text(payload, "Afkorting")
    name = first_text(payload, "NaamNL")
    acronym = _acronym(name)
    if (not abbreviation or abbreviation == name) and len(acronym) >= 2:
        if acronym in set(aliases):
            return acronym
    return abbreviation


def faction(
    payload: Payload, aliases: list[str], records: list[Payload] | None = None
) -> Record | None:
    """Node key and props for a faction: *payload* is its current Fractie record,
    *records* every record of it (the Kamer gives a faction that returns a new record, and
    still names the old one: 50PLUS 2012-2021 and again from 2025). The faction is active
    from the first record's start until the last one ends, and knows every record's id.
    ``None`` without an id or a name."""
    external_id = id_of(payload)
    label = faction_label(payload)
    if not external_id or not label:
        return None
    records = records or [payload]
    name = first_text(payload, "NaamNL")
    abbreviation = short_name(payload, aliases)
    starts = [d for d in (iso_date(r.get("DatumActief")) for r in records) if d]
    ends = [iso_date(r.get("DatumInactief")) for r in records]
    active = any(end is None for end in ends)
    return make_node_key(label), {
        "external_id": external_id,
        "external_ids": sorted({id_of(r) for r in records} - {""}),
        "name": name or abbreviation,
        "abbreviation": abbreviation or None,
        "aliases": aliases,
        "active_from": min(starts) if starts else None,
        "active_until": None if active else max(e for e in ends if e),
        # the Kamer keeps the seats a faction had on its record after it ended
        "seats": payload.get("AantalZetels") if active else 0,
        "active": active,
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
