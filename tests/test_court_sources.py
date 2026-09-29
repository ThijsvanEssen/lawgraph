"""The court table from the Instanties value list of the Rechtspraak, and its two levels.

The fixture is the value list as read on 29 September 2026.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lawgraph.core.court_sources import (
    MIXED_TIERS,
    TIER_OF_TYPE,
    build_courts,
    court_kind,
    parse_instanties,
    places,
)
from lawgraph.core.courts import COURT_KINDS, COURTS, DATA, OUTSIDE, TIERS, court_of

LIST = (Path(__file__).parent / "fixtures" / "rechtspraak_instanties.xml").read_text()
COURTS_LISTED = parse_instanties(LIST)
PLACES = places(COURTS_LISTED)


def test_the_data_file_is_what_the_value_list_gives() -> None:
    """``data/courts.json`` is the build of the fixture: nothing in it was edited by hand."""
    current = json.loads(DATA.read_text(encoding="utf-8"))
    assert build_courts(LIST) == current["courts"]


def test_every_type_of_the_list_has_a_tier_and_every_tier_is_listed() -> None:
    assert {c["type"] for c in COURTS_LISTED} <= set(TIER_OF_TYPE)
    assert {c.tier for c in COURTS} <= set(TIERS)
    assert set(COURT_KINDS) == {c.court_kind for c in COURTS}


@pytest.mark.parametrize(
    ("name", "tier", "kind"),
    [
        ("Hoge Raad", "hoge_raad", "hoge_raad"),
        ("Rechtbank Alkmaar", "rechtbank", "rechtbank"),
        ("Centraal Medisch Tuchtcollege", "tuchtcollege", "tuchtcollege"),
        ("Ambtenarengerecht 's-Gravenhage", "andere_instantie", "ambtenarengerecht"),
        ("Raad van beroep Alkmaar", "andere_instantie", "raad_van_beroep"),
        ("Tariefcommissie", "andere_instantie", "tariefcommissie"),
        (
            "College van Beroep voor het hoger onderwijs",
            "andere_instantie",
            "college_van_beroep_voor_het_hoger_onderwijs",
        ),
        (
            "Gerecht in eerste aanleg van Curaçao",
            "koninkrijksinstantie",
            "gerecht_in_eerste_aanleg",
        ),
        (
            "Gerecht in Eerste Aanleg Bonaire",
            "koninkrijksinstantie",
            "gerecht_in_eerste_aanleg",
        ),
        (
            "Constitutioneel Hof Sint Maarten",
            "koninkrijksinstantie",
            "constitutioneel_hof",
        ),
        (
            "Raad van Beroep in Ambtenarenzaken (Nederlandse Antillen en Aruba)",
            "koninkrijksinstantie",
            "raad_van_beroep_in_ambtenarenzaken",
        ),
        (
            "Hof van Justitie van de Nederlandse Antillen en Aruba",
            "koninkrijksinstantie",
            "hof_van_justitie",
        ),
    ],
)
def test_the_kind_of_a_court_is_its_name_without_the_place(
    name: str, tier: str, kind: str
) -> None:
    assert court_kind(name, tier, PLACES) == kind


def test_the_kinds_of_the_mixed_tiers() -> None:
    """Every court of a mixed tier has a kind shared with the courts of its kind only: no
    kind names a place."""
    kinds = {c.court_kind for c in COURTS if c.tier in MIXED_TIERS}
    assert kinds == {
        "ambtenarengerecht",
        "college_van_beroep_studiefinanciering",
        "college_van_beroep_voor_het_hoger_onderwijs",
        "raad_van_arbitrage_in_bouwgeschillen",
        "raad_van_beroep",
        "raad_voor_strafrechtstoepassing_en_jeugdbescherming",
        "tariefcommissie",
        "constitutioneel_hof",
        "gemeenschappelijk_hof_van_justitie",
        "gerecht_in_ambtenarenzaken",
        "gerecht_in_eerste_aanleg",
        "hof_van_justitie",
        "raad_van_beroep_in_ambtenarenzaken",
        "raad_van_beroep_voor_belastingzaken",
    }


def test_a_court_has_its_official_name_and_days() -> None:
    court = court_of("KTGALK")
    assert court is not None
    assert court.name == "Kantongerecht Alkmaar"
    assert court.until is not None  # the kantongerechten ended in 2002
    assert court_of("HR") is not None and court_of("HR").until is None  # type: ignore[union-attr]


def test_a_curated_court_is_one_the_list_does_not_hold() -> None:
    listed = {c["code"] for c in build_courts(LIST)}
    curated = json.loads(OUTSIDE.read_text(encoding="utf-8"))["courts"]
    assert all(c.get("court") or c["code"] not in listed for c in curated)
    assert all(c["tier"] in TIERS for c in curated)
