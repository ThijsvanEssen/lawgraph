"""Toezegging: a commitment of the government."""

from __future__ import annotations

from typing import Any

from lawgraph.core.display import shorten
from lawgraph.core.models import make_node_key
from lawgraph.core.time import iso_date
from lawgraph.core.tk_records._payload import (
    Payload,
    Record,
    dicts,
    distinct,
    first_text,
    id_of,
)
from lawgraph.core.tk_records.cases import dossier_numbers

# Toezegging.Status of a commitment still to be kept (the others: Afgedaan, Nagekomen, Niet
# nagekomen, Deels Afgedaan, Vervallen). A commitment keeps the Status the Kamer gives it.
COMMITMENT_OPEN = "Openstaand"


_COMMITMENT_TEXT_FIELDS = ("Tekst", "TekstAlgemeen", "TekstBrief")


# What a Toezegging holds as ``DatumNakoming`` when the Kamer names no date it is due.
NO_DUE_DATE = "0001-01-01"


def due_date(value: Any) -> str | None:
    """The day a commitment is due (``DatumNakoming``); None when the Kamer names none."""
    return value if value and value != NO_DUE_DATE else None


def made_on(payload: Payload) -> str | None:
    """The day a commitment was made: that of the activity it was made in (``Activiteit``,
    the debate), else the day the Kamer registered it (``Aanmaakdatum``, often weeks
    later)."""
    days = sorted(
        day
        for a in dicts(payload.get("Activiteit"))
        if (day := iso_date(a.get("Datum")))
    )
    return days[0] if days else iso_date(payload.get("Aanmaakdatum"))


def commitment(payload: Payload) -> Record | None:
    """Node key and props for a Toezegging record."""
    external_id = id_of(payload)
    if not external_id:
        return None

    text = first_text(payload, *_COMMITMENT_TEXT_FIELDS)
    letters = list(dicts(payload.get("KamerbriefNakoming")))
    raw_status = first_text(payload, "Status") or None
    return make_node_key(external_id), {
        "external_id": external_id,
        "text": text,
        "minister_name": first_text(payload, "Naam", "MinisterNaam"),
        "minister_role": first_text(payload, "Functie", "MinisterTitel"),
        # the ministry the Tweede Kamer gives the commitment (``Justitie en Veiligheid``)
        "ministry_name": first_text(payload, "Ministerie") or None,
        "made_on": made_on(payload),
        "registered_on": iso_date(payload.get("Aanmaakdatum")),
        "expected_resolution": iso_date(payload.get("DatumNakoming")),
        "status": raw_status,
        "activity_number": str(payload.get("ActiviteitNummer") or ""),
        "number": first_text(payload, "Nummer") or None,
        "display_name": shorten(text, 80),
        # the letters that fulfil it (``KamerbriefNakoming``): ANSWERS
        "letter_ids": distinct([str(d.get("Id") or "") for d in letters]),
        # the dossiers those letters are numbered in: ABOUT, before the agenda
        "letter_dossiers": dossier_numbers(letters),
    }
