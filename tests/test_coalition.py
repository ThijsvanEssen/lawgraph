"""The coalition of a cabinet day by day, and its seats over time (``core.coalition``)."""

from __future__ import annotations

from lawgraph.core.coalition import (
    TK_MAJORITY,
    coalition_on,
    seat_timeline,
    seats_on,
)


def _post(faction: str | None, start: str, end: str | None = None) -> dict:
    return {"party": {"faction": faction}, "from_date": start, "to_date": end}


def _seat(member: str, faction: str, start: str, end: str | None = None) -> dict:
    return {
        "member": member,
        "faction_key": faction,
        "from_date": start,
        "to_date": end,
    }


# Schoof as the posts give it: PVV's posts end on 3 June 2025, the others go on
POSTS = [
    _post("pvv", "2024-07-02", "2025-06-03"),
    _post("vvd", "2024-07-02"),
    _post("nsc", "2024-07-02"),
    _post(None, "2024-07-02"),  # partijloos: no faction
]


def test_a_party_leaves_the_coalition_when_its_last_post_ends() -> None:
    assert coalition_on(POSTS, "2025-06-03") == {"pvv", "vvd", "nsc"}
    assert coalition_on(POSTS, "2025-06-04") == {"vvd", "nsc"}


def test_a_member_is_one_seat_of_the_faction_of_that_day() -> None:
    seats = [
        _seat("a", "pvv", "2023-12-06", "2025-01-31"),
        _seat("a", "groep", "2025-02-01"),  # split off the PVV
        _seat("b", "pvv", "2023-12-06"),
    ]
    assert seats_on(seats, "2025-01-31") == {"pvv": 2}
    assert seats_on(seats, "2025-02-01") == {"pvv": 1, "groep": 1}


def test_the_seats_of_the_coalition_change_with_a_split_and_a_departure() -> None:
    seats = [
        _seat("a", "pvv", "2023-12-06", "2025-01-31"),
        _seat("a", "groep", "2025-02-01"),
        _seat("b", "pvv", "2023-12-06"),
        _seat("c", "vvd", "2023-12-06"),
        _seat("d", "sp", "2023-12-06"),
    ]
    timeline = seat_timeline(POSTS, seats, "2024-07-02", "2025-12-31")
    assert [
        (s["from_date"], s["to_date"], s["coalition"], s["opposition"])
        for s in timeline
    ] == [
        ("2024-07-02", "2025-01-31", 3, 1),
        # the split-off is a faction of its own without a post: opposition
        ("2025-02-01", "2025-06-03", 2, 2),
        # the PVV leaves the cabinet
        ("2025-06-04", "2025-12-31", 1, 3),
    ]
    assert [(f["key"], f["coalition"]) for f in timeline[1]["factions"]] == [
        ("pvv", True),
        ("vvd", True),
        ("groep", False),
        ("sp", False),
    ]
    assert TK_MAJORITY == 76
