"""Zaak: a case the Kamer handles, and the cases a record names."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from lawgraph.config.constants import SOURCE_TK
from lawgraph.core.models import make_node_key
from lawgraph.core.time import iso_date
from lawgraph.core.tk_records._payload import (
    Payload,
    Record,
    dicts,
    distinct,
    first_text,
    is_deleted,
)
from lawgraph.core.tk_records.dossiers import dossier_label
from lawgraph.core.tk_records.kinds import own_subject
from lawgraph.core.values import first_str


def case_ids(cases: Iterable[Payload]) -> list[str]:
    """Zaak GUIDs of the given Zaak records."""
    return distinct(str(record.get("Id") or "") for record in cases)


def _dossier_label(dossier: Payload) -> str:
    return dossier_label(dossier.get("Nummer"), dossier.get("Toevoeging"))


def dossier_numbers(cases: Iterable[Payload]) -> list[str]:
    """Kamerstukdossier labels (``37020``, ``37020-XV``) of the given Zaak records."""
    return distinct(
        _dossier_label(dossier)
        for record in cases
        for dossier in dicts(record.get("Kamerstukdossier"))
    )


def case_kinds(cases: Iterable[Payload]) -> list[str]:
    """Distinct ``Zaak.Soort`` values (Wetgeving, Motie, Amendement, …)."""
    return distinct(str(record.get("Soort") or "") for record in cases)


def case_kinds_by_dossier(cases: Iterable[Payload]) -> dict[str, list[str]]:
    """Distinct ``Zaak.Soort`` values (Wetgeving, Motie, …) per Kamerstukdossier label.

    Each dossier gets the kinds of its own cases only: one agenda (a day of votes) holds
    the cases of many dossiers.
    """
    pairs = [
        (_dossier_label(dossier), str(record.get("Soort") or ""))
        for record in cases
        for dossier in dicts(record.get("Kamerstukdossier"))
    ]
    numbers = distinct(number for number, _ in pairs)
    return {
        number: distinct(kind for n, kind in pairs if n == number) for number in numbers
    }


def case(payload: Payload) -> Record | None:
    """Node key and props for a Zaak record; ``None`` without an id.

    A motie, an amendement or a letter is named by its ``Onderwerp`` (``own_subject``): its
    ``Titel`` is the dossier's, the same for every motie on it.
    """
    external_id = first_str(
        [payload.get("Id"), payload.get("ZaakId"), payload.get("ZaakNummer")],
        skip_blank=True,
    )
    if external_id is None:
        return None
    kind = payload.get("Soort") or None
    title = own_subject(payload) or first_text(
        payload, "Titel", "ZaakTitel", "Onderwerp"
    )
    props: dict[str, Any] = {
        "source": SOURCE_TK,
        "external_id": external_id,
        "number": str(payload.get("Nummer") or payload.get("ZaakNummer") or ""),
        "kind": kind,
        # The dossiers this case belongs to; the dossier pipeline turns them into PART_OF
        # edges once the dossier nodes exist.
        "dossier_numbers": dossier_numbers([payload]),
        # Zaak.GestartOp: of a bill the day it was submitted, as the Kamer dates it
        "started_on": iso_date(payload.get("GestartOp")),
        # What `semantic tk-dossier-relations` lifts to RELATED_TO edges between dossiers.
        "related_cases": related_cases(payload),
        # The cases this one replaces, and their documents its documents (REVISES).
        "replaces_cases": replaced_cases(payload),
        # Zaak.Afgedaan: whether the Kamer is done with it (an amendment done with and
        # without a decision was replaced or withdrawn; one not done with is still open)
        "done": afgedaan
        if isinstance(afgedaan := payload.get("Afgedaan"), bool)
        else None,
    }
    if title:
        props["title"] = title
    if payload.get("Citeertitel"):
        props["citation_title"] = payload["Citeertitel"]
    props["display_name"] = title or f"Zaak {external_id}"
    return make_node_key(external_id), props


def related_cases(payload: Payload) -> list[dict[str, Any]]:
    """The cases the Kamer relates a Zaak to (``GerelateerdNaar``): id, kind and dossiers.

    Mostly a letter of the government and the motion it answers, or an amendment and its
    bill. The dossiers of the other case come with it, so the relation holds also when that
    case itself was not retrieved.
    """
    return [
        {
            "id": str(other["Id"]),
            "kind": str(other.get("Soort") or "") or None,
            "dossier_numbers": dossier_numbers([other]),
        }
        for other in dicts(payload.get("GerelateerdNaar"))
        if other.get("Id") and not is_deleted(other)
    ]


def replaced_cases(payload: Payload) -> list[str]:
    """The ids of the cases a Zaak replaces (``VervangenVanuit``): an amended amendment or
    motion, "ter vervanging van nr. 21", replaces the case of nr. 21."""
    return [
        str(other["Id"])
        for other in dicts(payload.get("VervangenVanuit"))
        if other.get("Id") and not is_deleted(other)
    ]


def agenda_cases(payload: Payload) -> list[Payload]:
    """The Zaak records on every Agendapunt of an Activiteit or Besluit."""
    return [
        record
        for item in dicts(payload.get("Agendapunt"))
        for record in dicts(item.get("Zaak"))
    ]
