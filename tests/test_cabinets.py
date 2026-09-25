"""Cabinets from Wikidata: name, key, parties, prime minister and the one in office; and who in
government made a commitment or brought a dossier in."""

from __future__ import annotations

from typing import Any

from lawgraph.clients.wikidata import group_cabinets, party_memberships
from lawgraph.core.cabinets import (
    INDEPENDENT,
    cabinet_key,
    cabinet_name,
    cabinet_on,
    cabinet_parties,
    faction_of,
    prime_minister,
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


def _party(qid: str, short: str, **dates: str) -> dict[str, Any]:
    return {"id": qid, "name": short, "short": short, **dates}


def _person(qid: str, *parties: dict[str, Any], start: str = "2022-01-10") -> dict:
    post = {
        "function": "minister van Financiën",
        "cabinet_id": RUTTE_IV,
        "from_date": start,
        "to_date": "2024-07-02",
    }
    return {"id": qid, "name": qid, "posts": [post], "parties": list(parties)}


def test_the_parties_of_a_cabinet_are_those_two_of_its_members_belonged_to() -> None:
    vvd, cu, pvda = (
        _party("Q1", "VVD"),
        _party("Q2", "CU"),
        _party("Q3", "PvdA", founded="1946-02-09"),
    )
    people = [
        _person("A", vvd),
        _person("B", vvd),
        _person("C", cu),
        _person("D", cu),
        # a PvdA member from outside the coalition: one member brings no party in
        _person("E", pvda),
        # an old party without dates beside the one they are in: counts for the latter
        _person("F", vvd, _party("Q4", "LPF", dissolved="2008-01-01")),
        _person(
            "H", _party(INDEPENDENT, "Ind."), _party("Q5", "X", founded="2023-01-01")
        ),
    ]
    parties = cabinet_parties(RUTTE_IV, people)
    assert [p["short"] for p in parties] == ["VVD", "CU"]
    assert cabinet_parties("Q-other", people) == []


def test_a_dated_membership_counts_only_while_it_lasts() -> None:
    old = _party("Q1", "PvdA", from_date="1990-01-01", to_date="2020-01-01")
    new = _party("Q2", "GL-PvdA", from_date="2020-01-01")
    people = [_person("A", old, new), _person("B", new)]
    assert [p["short"] for p in cabinet_parties(RUTTE_IV, people)] == ["GL-PvdA"]


def test_the_prime_minister_holds_the_post_else_heads_the_cabinet() -> None:
    cabinet = {"id": RUTTE_IV, "heads": ["QH"]}
    pm = {
        "id": "QP",
        "posts": [
            {"function": "minister-president van Nederland", "cabinet_id": RUTTE_IV}
        ],
    }
    assert prime_minister(cabinet, [_person("A"), pm]) == "QP"
    assert prime_minister(cabinet, [_person("A")]) == "QH"


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


def test_the_wikidata_rows_become_cabinets_and_party_memberships() -> None:
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
            "head": {"value": E + "Q57792"},
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
            "heads": ["Q57792"],
            "previous": ["Q42293409"],
        }
    ]
    memberships = party_memberships(
        [
            {
                "person": {"value": E + "Q1"},
                "party": {"value": E + "Q2"},
                "partyLabel": {"value": "Volkspartij voor Vrijheid en Democratie"},
                "short": {"value": "VVD"},
                "from": {"value": "1990-01-01T00:00:00Z"},
            }
        ]
    )
    assert memberships["Q1"][0]["short"] == "VVD"
    assert memberships["Q1"][0]["from_date"] == "1990-01-01"


def test_the_api_knows_every_status_a_commitment_can_have() -> None:
    from typing import get_args

    from lawgraph.api.schemas.government import CommitmentStatus
    from lawgraph.core.tk_records import COMMITMENT_STATUS

    assert set(get_args(CommitmentStatus)) == set(COMMITMENT_STATUS.values())


def _cabinet(qid, start, start_p, end=None, end_p=None, previous=()):
    return {
        "id": qid,
        "from_date": start,
        "from_date_precision": start_p,
        "to_date": end,
        "to_date_precision": end_p,
        "previous": list(previous),
    }


def test_a_cabinet_without_an_end_ends_when_the_next_one_starts() -> None:
    from lawgraph.core.cabinets import complete_periods

    periods = complete_periods(
        [
            _cabinet("A", "1879-08-20", 11, "1883-04-23", 11),
            # Wikidata lacks the cabinet of 1883-1888: the year stays a year
            _cabinet("B", "1888-01-01", 9),
            _cabinet("C", "1891-01-01", 9),
            # an end in the year the next one starts, known to the day
            _cabinet("D", "1901-01-01", 9, "1905-01-01", 9),
            _cabinet("E", "1905-08-17", 11, "1908-02-12", 11),
            _cabinet("F", "1908-01-01", 9, previous=["E"]),
            _cabinet("G", "2026-02-23", 11),
        ]
    )
    assert periods["B"] == {
        "from_date": "1888-01-01",
        "from_date_precision": "year",
        "to_date": "1891-01-01",
        "to_date_precision": "year",
        "previous": "A",
    }
    assert (periods["D"]["to_date"], periods["D"]["to_date_precision"]) == (
        "1905-08-17",
        "day",
    )
    assert (periods["F"]["from_date"], periods["F"]["from_date_precision"]) == (
        "1908-02-12",
        "day",
    )
    assert periods["F"]["previous"] == "E"
    assert periods["A"]["previous"] is None
    # only the cabinet in office has no end
    assert [q for q, p in periods.items() if p["to_date"] is None] == ["G"]
