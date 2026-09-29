"""The courts from the official source: the Instanties value list of the Rechtspraak.

``data/courts.json`` holds the courts ``core.courts`` reads. ``build_courts`` makes it from
the value list ``https://data.rechtspraak.nl/Waardelijst/Instanties``: every court an ECLI
can name, with its code (``Afkorting``, the court part of the ECLI), its official name, its
``Type`` and the days it existed. What the list does not hold is kept by hand in
``data/curated/courts_outside.json``: the EHRM's own code, and the courts outside the
Netherlands the Rechtspraak publishes under code ``XX`` (the Kroon, the EHRM, the Court of
Justice of the EU).

A court has two levels:

- **tier**, coarse: the ``Type`` the list gives it (``TIER_OF_TYPE``). The highest courts
  and the parket each have a type of their own; the courts of one kind share one; every
  other college is ``andere_instantie`` and every court of the Caribbean part of the
  Kingdom ``koninkrijksinstantie``.
- **court_kind**, fine: the kind of court within the tier, from its official name
  (``court_kind``). A tier of one kind of court is its own court_kind.
"""

from __future__ import annotations

import re
import unicodedata
import xml.etree.ElementTree as ET
from typing import Any

TIER_HOGE_RAAD = "hoge_raad"
TIER_RAAD_VAN_STATE = "raad_van_state"
TIER_CENTRALE_RAAD = "centrale_raad_van_beroep"
TIER_CBB = "college_van_beroep_bedrijfsleven"
TIER_PARKET = "parket"  # the Parket bij de Hoge Raad: conclusions, no judgments
TIER_GERECHTSHOF = "gerechtshof"
TIER_RECHTBANK = "rechtbank"
TIER_KANTONGERECHT = "kantongerecht"  # until 2002
TIER_TUCHTCOLLEGE = "tuchtcollege"  # every disciplinary tribunal
TIER_KONINKRIJK = (
    "koninkrijksinstantie"  # the courts of Aruba, Curaçao, Sint Maarten, BES
)
TIER_ANDERE = "andere_instantie"  # every other college
TIER_BUITENLAND = "buitenlandse_instantie"  # code XX: a court outside the Netherlands
# No type of the list: the courts it publishes under code XX, and the EHRM.
TIER_KROON = "kroon"  # a decision of the Crown on an appeal (Kroonberoep)
TIER_HVJ_EU = "hvj_eu"  # the Court of Justice of the European Union
TIER_EHRM = "ehrm"  # the European Court of Human Rights

TIER_OF_TYPE = {
    "TypeHr": TIER_HOGE_RAAD,
    "TypeRvS": TIER_RAAD_VAN_STATE,
    "TypeCRvB": TIER_CENTRALE_RAAD,
    "TypeCBb": TIER_CBB,
    "Parket": TIER_PARKET,
    "Gerechtshof": TIER_GERECHTSHOF,
    "Rechtbank": TIER_RECHTBANK,
    "Kantongerecht": TIER_KANTONGERECHT,
    "TuchtrechtelijkeInstantie": TIER_TUCHTCOLLEGE,
    "Koninkrijksinstantie": TIER_KONINKRIJK,
    "AndereGerechtelijkeInstantie": TIER_ANDERE,
    "http://psi.rechtspraak.nl/buitenlandseInstantie": TIER_BUITENLAND,
}
# The tiers whose courts are of more than one kind: their court_kind comes from the name.
MIXED_TIERS = frozenset({TIER_KONINKRIJK, TIER_ANDERE})

# The countries of the Kingdom a Caribbean court is named after.
_KINGDOM = (
    r"(?:de\s+)?(?:Nederlandse\s+Antillen|Aruba|Cura[cç]ao|Sint\s+Maarten|Bonaire)\b"
)
_BRACKETS = re.compile(r"\s*\([^)]*\)")
_OF_KINGDOM = re.compile(rf"\s+(?:(?:van|voor)\s+)?{_KINGDOM}.*$", re.IGNORECASE)


def slug(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text)
    plain = "".join(c for c in plain if not unicodedata.combining(c)).lower()
    return "_".join(re.findall(r"[a-z0-9]+", plain))


def parse_instanties(xml_text: str) -> list[dict[str, Any]]:
    """``{code, name, type, from, until}`` of every court of the value list; ``code`` is
    ``None`` for a court without one (the military and colonial courts)."""
    courts = []
    for item in ET.fromstring(xml_text):
        fields = {child.tag: (child.text or "").strip() for child in item}
        courts.append(
            {
                "code": fields.get("Afkorting") or None,
                "name": fields.get("Naam", ""),
                "type": fields.get("Type", ""),
                "from": fields.get("BeginDate") or None,
                "until": fields.get("EndDate") or None,
            }
        )
    return courts


def places(courts: list[dict[str, Any]]) -> set[str]:
    """The places the list names its courts after: the name of every rechtbank,
    kantongerecht and gerechtshof without its first word (``Rechtbank Alkmaar``)."""
    return {
        " ".join(c["name"].split()[1:])
        for c in courts
        if TIER_OF_TYPE.get(c["type"])
        in (TIER_RECHTBANK, TIER_KANTONGERECHT, TIER_GERECHTSHOF)
        and len(c["name"].split()) > 1
    }


def court_kind(name: str, tier: str, known_places: set[str]) -> str:
    """The kind of a court: its tier, for a tier of one kind; else its official name
    without the place, in lower case and joined by ``_``.

    The place is what follows the kind: a part in brackets, a country of the Kingdom (with
    ``van``/``voor`` before it: ``Gerecht in eerste aanleg van Curaçao``), or at the end a
    place the list names a rechtbank, kantongerecht or gerechtshof after (``Raad van
    beroep Alkmaar``)."""
    if tier not in MIXED_TIERS:
        return tier
    text = _OF_KINGDOM.sub("", _BRACKETS.sub("", name)).strip()
    for place in sorted(known_places, key=len, reverse=True):
        if text.endswith(f" {place}"):
            text = text[: -len(place) - 1]
            break
    return slug(text)


def build_courts(xml_text: str) -> list[dict[str, Any]]:
    """The court table: every court of the value list with a code, in its order."""
    listed = parse_instanties(xml_text)
    known = places(listed)
    return [
        {
            "code": court["code"],
            "name": court["name"],
            "type": court["type"],
            "tier": TIER_OF_TYPE[court["type"]],
            "court_kind": court_kind(court["name"], TIER_OF_TYPE[court["type"]], known),
            "from": court["from"],
            "until": court["until"],
        }
        for court in listed
        if court["code"] and court["type"] in TIER_OF_TYPE
    ]
