"""Whether a member has a role (``core.member_role``), how search ranks those without one, and
the day a person of the Tweede Kamer died."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.core.member_role import has_role, is_minister
from lawgraph.core.tk_records.members import member
from lawgraph.db.queries.search.ranking import rank_hits
from tests.member_role_cases import CASES


@pytest.mark.parametrize(("props", "expected"), CASES)
def test_a_role_is_a_seat_or_a_post(props: dict[str, Any], expected: bool) -> None:
    assert has_role(props) is expected


_TODAY = "2026-10-28"
_POST_NOW = {"from_date": "2026-02-23", "to_date": None}
_POST_OLD = {"from_date": "2022-01-10", "to_date": "2023-07-07"}
_SEAT_NOW = {"from_date": "2023-12-06", "to_date": None}
_SEAT_OLD = {"from_date": "2017-03-23", "to_date": "2021-03-30"}


@pytest.mark.parametrize(
    ("props", "expected"),
    [
        ({}, False),
        ({"faction_memberships": [_SEAT_NOW]}, False),
        ({"government_functions": [_POST_NOW]}, True),
        # a post that lasts outweighs a seat that lasts
        (
            {"government_functions": [_POST_NOW], "faction_memberships": [_SEAT_NOW]},
            True,
        ),
        # a past post and a seat that lasts: a Kamerlid again
        (
            {"government_functions": [_POST_OLD], "faction_memberships": [_SEAT_NOW]},
            False,
        ),
        # both ended: the role that ended last
        (
            {"government_functions": [_POST_OLD], "faction_memberships": [_SEAT_OLD]},
            True,
        ),
        ({"government_functions": [_POST_OLD]}, True),
    ],
)
def test_the_current_role_is_minister_or_kamerlid(
    props: dict[str, Any], expected: bool
) -> None:
    assert is_minister(props, _TODAY) is expected


def test_search_lists_a_member_without_a_role_after_those_with_one() -> None:
    hits = [
        {
            "key": "j_de_vries",
            "display_name": "J. de Vries",
            "extra": {"has_role": False},
        },
        {
            "key": "jan_de_vries",
            "display_name": "Jan de Vries",
            "extra": {"has_role": True},
        },
    ]
    # the exact name of the one without a role scores higher, and still comes last
    assert [h["key"] for h in rank_hits("J. de Vries", hits)] == [
        "jan_de_vries",
        "j_de_vries",
    ]


def test_a_person_has_the_day_they_died() -> None:
    record = member(
        {
            "Id": "b153ff84-388e-41a4-a0d9-e1be6dc00d04",
            "Initialen": "PJHM",
            "Achternaam": "Luijten",
            "Geboortedatum": "1924-04-28T00:00:00",
            "Overlijdensdatum": "2009-01-05T00:00:00",
        }
    )
    assert record is not None
    assert (record[1]["birth_date"], record[1]["death_date"]) == (
        "1924-04-28",
        "2009-01-05",
    )
