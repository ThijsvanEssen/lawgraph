"""Whether a member has a role (``core.member_role``), how search ranks those without one, and
the day a person of the Tweede Kamer died."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.core import tk_records
from lawgraph.core.member_role import has_role
from lawgraph.db.queries.search import rank_hits

# props of a member, and whether they hold a role
CASES: list[tuple[dict[str, Any], bool]] = [
    ({"faction_memberships": [{"faction_key": "d66"}]}, True),
    ({"government_functions": [{"function": "Minister-president"}]}, True),
    ({"ek_faction_memberships": [{"faction": "PvdA"}]}, True),
    ({"ek": {"faction": "ek_d66"}}, True),
    ({}, False),
    ({"faction_memberships": [], "government_functions": []}, False),
    ({"ek": None, "ek_faction_memberships": None}, False),
    ({"faction_memberships": "d66"}, False),  # not a list
]


@pytest.mark.parametrize(("props", "expected"), CASES)
def test_a_role_is_a_seat_or_a_post(props: dict[str, Any], expected: bool) -> None:
    assert has_role(props) is expected


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
    record = tk_records.member(
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
