"""Activiteit: a debate, a meeting, the votes."""

from __future__ import annotations

from lawgraph.core.models import make_node_key
from lawgraph.core.time import iso_date
from lawgraph.core.tk_records._payload import (
    Payload,
    Record,
    dicts,
    first_text,
    id_of,
)
from lawgraph.core.tk_records.cases import (
    agenda_cases,
    case_ids,
    case_kinds_by_dossier,
    dossier_numbers,
)
from lawgraph.core.tk_records.committees import PLENARY_VOORTOUW


def activity(payload: Payload) -> Record | None:
    """Node key and props for an Activiteit record."""
    external_id = id_of(payload)
    if not external_id:
        return None

    cases = agenda_cases(payload)
    date = iso_date(payload.get("Datum"))
    description = first_text(payload, "Onderwerp")
    kind = payload.get("Soort") or ""
    voortouw = payload.get("Voortouwcommissie_Id")
    # A plenary activity has the Kamer itself as voortouw, not a committee.
    plenary = payload.get("Voortouwafkorting") == PLENARY_VOORTOUW

    return make_node_key(external_id), {
        "external_id": external_id,
        "date": date,
        # how precise the date is: a day, or the Monday of a week planned, or the first
        # day of several
        "precision": first_text(payload, "DatumSoort") or None,
        "agenda_title": description,
        "kind": kind,
        "status": first_text(payload, "Status") or None,
        "committee_id": str(voortouw) if voortouw and not plenary else None,
        "case_ids": case_ids(cases),
        "dossier_numbers": dossier_numbers(cases),
        "case_kinds_by_dossier": case_kinds_by_dossier(cases),
        "display_name": activity_display_name(date, description or kind),
        "number": str(payload.get("Nummer") or ""),
        # the activities a moved one was replaced by (Activiteit.VervangenDoor): a moved
        # activity keeps no agenda, the one that replaced it has it
        "replaced_by": [
            str(other["Nummer"])
            for other in dicts(payload.get("VervangenDoor"))
            if other.get("Nummer")
        ],
    }


def activity_display_name(date: str | None, subject: str | None) -> str:
    """``Digitale grondrechten en data-ethiek (2027-02-11)``: the subject, then the day."""
    subject = subject or "Activiteit"
    return f"{subject} ({date})" if date else subject
