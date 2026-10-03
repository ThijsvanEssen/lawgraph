"""The item XML of a treaty in the Verdragenbank (``repository.overheid.nl/frbr/vd/…``).

The SRU record of a treaty gives its title, dates, type and status. The item XML it links to
(``gzd:url``) gives the rest of the register's page:

- ``Tractatenbladen``: the Tractatenblad publications of the treaty, each "1951, 154" with a
  description ("goedkeuring, inwerkingtreding", "partijgegevens");
- ``Partijen``: the states party to it, each with the dates of signature, ratification (or
  another consent: ``TypeInstemming``), provisional application, entry into force,
  denunciation and termination, and whether it made reservations or objections;
- ``Koninkrijksdelen``: the parts of the Kingdom it applies to, and from when;
- ``Kamerstukken``: the dossiers of its approval;
- ``Moederverdragen`` and ``Kindverdragen``: the treaty it belongs to (a Protocol to its
  Convention) and those that belong to it.

Values as the source writes them; a date is ``YYYY-MM-DD``, an empty or ``xsi:nil`` element
none. The text of a reservation is not kept: whether there is one is, and the register's page
of the parties has the text (``reservations_url``).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

from lawgraph.core.xml import local_name

# "1951, 154", "1964, 163": year and number of a Tractatenblad.
_TRB_TEXT = re.compile(r"^\s*(\d{4})\s*,\s*(\d+)\s*$")
# The register's page of the parties of a treaty, its reservations and objections among them.
_RESERVATIONS_URL = "https://verdragenbank.overheid.nl/nl/Verdrag/Details/{treaty_id}_p.html#Voorbehouden"


def _children(element: ET.Element | None, name: str) -> list[ET.Element]:
    if element is None:
        return []
    return [child for child in element if local_name(child.tag) == name]


def _first(element: ET.Element | None, name: str) -> ET.Element | None:
    return next(iter(_children(element, name)), None)


def _text(element: ET.Element | None, name: str) -> str | None:
    """The text of the child *name* of *element*: None when absent, empty or nil."""
    child = _first(element, name)
    text = (child.text or "").strip() if child is not None else ""
    return text or None


def _flag(element: ET.Element, name: str) -> bool | None:
    text = _text(element, name)
    return None if text is None else text.lower() == "true"


def trb_official_id(text: str | None) -> str | None:
    """``trb-1951-154`` for the Tractatenblad "1951, 154": its id on
    officielebekendmakingen.nl. None for a text that is no year and number."""
    match = _TRB_TEXT.match(text or "")
    return f"trb-{match[1]}-{int(match[2])}" if match else None


def reservations_url(
    treaty_id: str | None, parties: list[dict[str, Any]]
) -> str | None:
    """The register's page with the reservations and objections of the parties to the treaty
    *treaty_id*; None when no party made one."""
    if not treaty_id or not any(
        p.get("reservation") or p.get("objection") for p in parties
    ):
        return None
    return _RESERVATIONS_URL.format(treaty_id=treaty_id)


def _anywhere(root: ET.Element, name: str) -> ET.Element | None:
    """The first element *name* of the document: the Tractatenbladen and Kamerstukken stand
    in its meta part, not in ``<verdrag>``."""
    return next((e for e in root.iter() if local_name(e.tag) == name), None)


def _tractatenblad(root: ET.Element) -> list[dict[str, Any]]:
    found = []
    for trb in _children(_anywhere(root, "Tractatenbladen"), "Tractatenblad"):
        text = _text(trb, "TractatenbladText")
        if text:
            found.append(
                {
                    "official_id": trb_official_id(text),
                    "text": text,
                    "description": _text(trb, "Omschrijving"),
                }
            )
    return found


def _parties(verdrag: ET.Element) -> list[dict[str, Any]]:
    found = []
    for party in _children(_first(verdrag, "Partijen"), "Partij"):
        name = _text(party, "NaamPartij")
        if not name:
            continue
        found.append(
            {
                "name": name,
                # the source spells the element "DatumOndertekenning"
                "signed": _text(party, "DatumOndertekenning"),
                "ratified": _text(party, "DatumRatificatie"),
                "consent": _text(party, "TypeInstemming"),
                "provisional": _text(party, "DatumVoorlopigeToepassing"),
                "in_force": _text(party, "DatumInwerkingtreding"),
                "retroactive": _text(party, "DatumTerugwerkendeKracht"),
                "denounced": _text(party, "DatumOpzegging"),
                "terminated": _text(party, "DatumBuitenwerkingtreding"),
                "reservation": _flag(party, "IsVoorbehoud"),
                "objection": _flag(party, "IsBezwaar"),
            }
        )
    return found


def _kingdom_parts(verdrag: ET.Element) -> list[dict[str, Any]]:
    return [
        {
            "part": _text(part, "NaamKoninkrijksdeel"),
            "provisional": _text(part, "DatumVoorlopigeToepassing"),
            "in_force": _text(part, "DatumInwerkingtreding"),
            "retroactive": _text(part, "DatumTerugwerkendeKracht"),
            "terminated": _text(part, "DatumBuitenwerkingtreding"),
        }
        for part in _children(_first(verdrag, "Koninkrijksdelen"), "Koninkrijksdeel")
        if _text(part, "NaamKoninkrijksdeel")
    ]


def _kamerstukken(root: ET.Element) -> list[dict[str, Any]]:
    """The dossiers of its approval, each once, in order: the dossier number, and the
    number of a rijkswet (``R2188``) and the sub-number as the source writes them."""
    found: list[dict[str, Any]] = []
    for paper in _children(_anywhere(root, "Kamerstukken"), "Kamerstuk"):
        dossier = _text(paper, "DossierNummer") or _text(paper, "KamerstukDossier")
        if not dossier:
            continue
        entry = {
            "dossier": dossier,
            "rijks_number": _text(paper, "RijksNummer"),
            "sub_number": _text(paper, "OnderNummer"),
        }
        if entry not in found:
            found.append(entry)
    return found


def _related(verdrag: ET.Element, group: str, prefix: str) -> list[dict[str, Any]]:
    """``Moederverdragen`` (*prefix* ``Moeder``) or ``Kindverdragen`` (``Kind``)."""
    return [
        {
            "id": _text(treaty, f"{prefix}VerdragID"),
            "title": _text(treaty, f"Titel{prefix}Verdrag"),
            "date": _text(treaty, f"Datum{prefix}Verdrag"),
            "place": _text(treaty, f"Plaats{prefix}Verdrag"),
        }
        for treaty in _children(_first(verdrag, group), f"{prefix}verdrag")
        if _text(treaty, f"{prefix}VerdragID")
    ]


def _place_signed(root: ET.Element) -> str | None:
    place = _anywhere(root, "sluitingsPlaats")
    return ((place.text or "").strip() or None) if place is not None else None


def parse_treaty_xml(xml_text: str) -> dict[str, Any]:
    """The props the item XML of a treaty adds: ``place_signed``, ``tractatenblad``,
    ``parties``, ``kingdom_parts``, ``kamerstukken``, ``parent_treaties`` and
    ``child_treaties``. ``ValueError`` when *xml_text* is no treaty of the register."""
    try:
        root = ET.fromstring(xml_text.lstrip("﻿"))
    except ET.ParseError as exc:
        raise ValueError(f"not XML: {exc}") from exc
    verdrag = next((e for e in root.iter() if local_name(e.tag) == "verdrag"), None)
    if verdrag is None:
        raise ValueError("no <verdrag> in the item XML")
    return {
        "place_signed": _place_signed(root),
        "tractatenblad": _tractatenblad(root),
        "parties": _parties(verdrag),
        "kingdom_parts": _kingdom_parts(verdrag),
        "kamerstukken": _kamerstukken(root),
        "parent_treaties": _related(verdrag, "Moederverdragen", "Moeder"),
        "child_treaties": _related(verdrag, "Kindverdragen", "Kind"),
    }
