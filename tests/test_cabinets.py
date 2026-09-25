"""Cabinets: name, key, period, the faction of a party and the one in office; and who in
government made a commitment or brought a dossier in."""

from __future__ import annotations

from lawgraph.clients.wikidata import group_cabinets
from lawgraph.core.cabinets import (
    cabinet_key,
    cabinet_name,
    cabinet_on,
    faction_of,
)
from lawgraph.pipelines.semantic.tk_government import commitment_props, dossier_props

E = "http://www.wikidata.org/entity/"
RUTTE_IV = "Q110111120"


def test_every_spelling_of_a_cabinet_has_one_name_and_key() -> None:
    assert cabinet_name("Kabinet-Balkenende II (2003-2006)") == "kabinet-Balkenende II"
    assert cabinet_name("Kabinet Balkenende I (2002-2003)") == "kabinet-Balkenende I"
    assert cabinet_name("kabinet-Rutte III") == "kabinet-Rutte III"
    assert cabinet_key("kabinet-Balkenende II") == "balkenende_ii"
    assert cabinet_key("kabinet-Den Uyl") == "den_uyl"
    assert cabinet_key("kabinet-Röell") == "roell"
    assert cabinet_key(cabinet_name("Kabinet-Schermerhorn-Drees (1945-1946)")) == (
        "schermerhorn_drees"
    )


def test_a_party_is_the_faction_that_bears_its_name_or_abbreviation() -> None:
    factions = [
        {"key": "christenunie", "name": "ChristenUnie", "abbreviation": "ChristenUnie"},
        {
            "key": "vvd",
            "name": "Volkspartij voor Vrijheid en Democratie",
            "abbreviation": "VVD",
        },
    ]
    assert (
        faction_of({"name": "ChristenUnie", "short": "CU"}, factions) == "christenunie"
    )
    assert faction_of({"name": "x", "short": "VVD"}, factions) == "vvd"
    assert (
        faction_of({"name": "Katholieke Volkspartij", "short": "KVP"}, factions) is None
    )
    # a faction without an abbreviation: the capitals of its name
    nsc = [*factions, {"key": "nsc", "name": "Nieuw Sociaal Contract"}]
    assert faction_of({"name": "NSC", "short": "NSC"}, nsc) == "nsc"
    assert faction_of({"name": "CU", "short": "CU"}, nsc) == "christenunie"


CABINETS = [
    {"key": "rutte_iv", "from_date": "2022-01-10", "to_date": "2024-07-02"},
    {"key": "schoof", "from_date": "2024-07-02", "to_date": "2026-02-23"},
    {"key": "jetten", "from_date": "2026-02-23", "to_date": None},
]


def test_the_cabinet_in_office_on_a_day_is_the_new_one_on_the_handover() -> None:
    assert cabinet_on("2023-05-01", CABINETS) == "rutte_iv"
    assert cabinet_on("2024-07-02", CABINETS) == "schoof"
    assert cabinet_on("2030-01-01", CABINETS) == "jetten"
    assert cabinet_on("2000-01-01", CABINETS) is None
    assert cabinet_on(None, CABINETS) is None


def test_a_commitment_is_made_by_whoever_held_such_a_post_that_day() -> None:
    herbert = {
        "id": "herbert",
        "name": "Heleen Herbert",
        "posts": [
            {
                "function": "Minister van Economische Zaken",
                "from_date": "2026-02-23",
                "to_date": None,
            }
        ],
    }
    row = {
        "name": "Herbert, H.G.",
        "role": "Minister van Economische Zaken",
        "date": "2026-03-19",
    }
    assert commitment_props(row, [herbert], CABINETS) == {
        "member_key": "herbert",
        "post": "minister",
        "ministry": "ez",
        "cabinet": "jetten",
    }
    # before the post began: nobody fits
    assert (
        commitment_props({**row, "date": "2020-01-01"}, [herbert], CABINETS)[
            "member_key"
        ]
        is None
    )


def test_a_dossier_is_brought_in_by_its_first_signatory() -> None:
    minister = {
        "date": "2023-05-01",
        "capacity": "bewindspersoon",
        "function": "minister van Financiën",
    }
    assert dossier_props(minister, CABINETS) == {
        "ministry": "fin",
        "initiative": False,
        "cabinet": "rutte_iv",
    }
    member = {
        "date": "2025-01-01",
        "capacity": "kamerlid",
        "function": "Tweede Kamerlid",
    }
    assert dossier_props(member, CABINETS) == {
        "ministry": None,
        "initiative": True,
        "cabinet": "schoof",
    }
    assert dossier_props(None, CABINETS) == {
        "ministry": None,
        "initiative": None,
        "cabinet": None,
    }


def test_the_wikidata_rows_become_cabinets() -> None:
    rows = [
        {
            "cabinet": {"value": E + RUTTE_IV},
            "cabinetLabel": {"value": "kabinet-Rutte IV"},
            "inception": {"value": "2022-01-10T00:00:00Z"},
            "inceptionPrecision": {"value": "11"},
            # the end of the term, known to the year only, and the dissolution to the day
            "end": {"value": "2024-01-01T00:00:00Z"},
            "endPrecision": {"value": "9"},
            "dissolved": {"value": "2024-07-02T00:00:00Z"},
            "dissolvedPrecision": {"value": "11"},
            "previous": {"value": E + "Q42293409"},
        }
    ]
    assert group_cabinets(rows) == [
        {
            "id": RUTTE_IV,
            "name": "kabinet-Rutte IV",
            "from_date": "2022-01-10",
            "from_date_precision": 11,
            "to_date": "2024-07-02",
            "to_date_precision": 11,
            "previous": ["Q42293409"],
        }
    ]


def test_the_api_knows_every_status_a_commitment_can_have() -> None:
    from typing import get_args

    from lawgraph.api.schemas.government import CommitmentStatus
    from lawgraph.core.tk_records import COMMITMENT_STATUS

    assert set(get_args(CommitmentStatus)) == set(COMMITMENT_STATUS.values())


def test_a_wikidata_period_is_what_wikidata_gives() -> None:
    from lawgraph.core.cabinets import wikidata_period

    # De Geer II: known to the year, without an end; nothing is taken from its neighbours
    assert wikidata_period(
        {"from_date": "1939-01-01", "from_date_precision": 9, "to_date": None}
    ) == {
        "from_date": "1939-01-01",
        "from_date_precision": "year",
        "to_date": None,
        "to_date_precision": None,
    }
    assert (
        wikidata_period(
            {
                "from_date": "1848-03-25",
                "from_date_precision": 11,
                "to_date": "1848-11-21",
                "to_date_precision": 11,
            }
        )["to_date_precision"]
        == "day"
    )
