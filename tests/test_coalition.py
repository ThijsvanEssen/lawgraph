"""The coalition of a cabinet day by day, and its seats over time (``core.coalition``)."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.core.coalition import (
    TK_MAJORITY,
    coalition_on,
    seat_timeline,
    seats_on,
    tk_events,
    vote_pattern,
)
from lawgraph.core.seat_periods import one_faction_at_a_time
from lawgraph.pipelines.semantic.tk_coalition_votes import _decision_row, _per_decision
from tests.asserts import show_items


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


COALITION = {"pvv", "vvd", "nsc", "bbb"}


def test_a_vote_the_coalition_carries_together() -> None:
    votes = [("pvv", "Voor", 37), ("vvd", "Voor", 24), ("nsc", "Voor", 20)]
    votes += [("bbb", "Voor", 7), ("gl", "Tegen", 25), ("d66", "Tegen", 9)]
    result = vote_pattern(votes, COALITION)
    assert result is not None
    assert (result["coalition_for"], result["opposition_against"]) == (88, 34)
    assert result["pattern"] == "together"
    assert result["passed"] and result["carried"]
    # the opposition alone: 7 for, 34 against — the coalition decided
    assert result["decisive"]


def test_a_vote_the_opposition_alone_would_have_passed_too_is_not_decisive() -> None:
    """Decisive: the opposition alone would have decided otherwise. A coalition with a
    majority could always turn a vote, so that says nothing."""
    votes = [("pvv", "Voor", 37), ("vvd", "Voor", 24), ("nsc", "Voor", 20)]
    votes += [("bbb", "Voor", 7), ("gl", "Voor", 25), ("d66", "Tegen", 9)]
    result = vote_pattern(votes, COALITION)
    assert result is not None and result["passed"] and result["carried"]
    assert not result["decisive"]


def test_the_coalition_majority_winning_with_the_opposition_is_a_split() -> None:
    """VVD and NSC (44) for, PVV (37) against: the side with the most coalition seats wins,
    with part of the opposition. The coalition is split; no wisselmeerderheid."""
    votes = [("pvv", "Tegen", 37), ("vvd", "Voor", 24), ("nsc", "Voor", 20)]
    votes += [
        ("bbb", "Tegen", 7),
        ("gl", "Voor", 25),
        ("d66", "Voor", 9),
        ("sp", "Tegen", 5),
    ]
    result = vote_pattern(votes, COALITION)
    assert result is not None
    assert result["pattern"] == "split" and result["passed"]
    assert not result["carried"]


def test_a_wisselmeerderheid_beats_the_coalition_majority() -> None:
    """PVV and VVD (61) against, NSC (20) for with the opposition: the side with the most
    coalition seats loses. A wisselmeerderheid."""
    votes = [("pvv", "Tegen", 37), ("vvd", "Tegen", 24), ("nsc", "Voor", 20)]
    votes += [
        ("bbb", "Voor", 7),
        ("gl", "Voor", 25),
        ("d66", "Voor", 9),
        ("sp", "Voor", 5),
    ]
    result = vote_pattern(votes, COALITION)
    assert result is not None
    assert result["pattern"] == "wissel" and result["passed"]
    assert not result["carried"]
    # the opposition alone passed it too: the coalition did not decide
    assert not result["decisive"]


def test_a_split_coalition_on_the_losing_side_is_no_wissel() -> None:
    # passed by the coalition's own majority for; one coalition party against with nobody
    votes = [("pvv", "Voor", 37), ("vvd", "Voor", 24), ("nsc", "Tegen", 20)]
    votes += [("bbb", "Voor", 7), ("gl", "Tegen", 25)]
    result = vote_pattern(votes, COALITION)
    assert result is not None
    # the winning side (for) holds coalition seats only: split, no wissel
    assert result["pattern"] == "split" and result["passed"] and result["carried"]


def test_without_a_coalition_vote_there_is_no_pattern() -> None:
    assert vote_pattern([("gl", "Voor", 25)], COALITION) is None
    assert vote_pattern([("pvv", "Niet deelgenomen", 37)], COALITION) is None


def test_a_tie_is_rejected_and_the_opposition_decides_without_the_coalition() -> None:
    votes = [("pvv", "Voor", 10), ("gl", "Tegen", 10)]
    result = vote_pattern(votes, {"pvv"})
    assert result is not None and not result["passed"]
    # a large opposition majority: the coalition could not have turned it
    big = vote_pattern([("pvv", "Voor", 10), ("gl", "Tegen", 100)], {"pvv"})
    assert big is not None and not big["decisive"]


def test_a_seat_between_two_members_is_vacant_so_the_kamer_adds_up() -> None:
    """Kabinet-Jetten, 23 February 2026: members who became bewindspersonen left on the
    22nd, their successors came on the 25th; the source records the seats as vacant."""
    posts = [_post("d66", "2026-02-23")]
    seats = [_seat(f"m{n}", "d66", "2025-11-12") for n in range(139)]
    seats += [_seat(f"left{n}", "d66", "2025-11-12", "2026-02-22") for n in range(11)]
    seats += [_seat(f"new{n}", "d66", "2026-02-25") for n in range(11)]
    timeline = seat_timeline(posts, seats, "2026-02-23", "2026-03-01")
    assert [
        (s["from_date"], s["coalition"], s["vacant"], s["coalition_vacant"])
        for s in timeline
    ] == [
        ("2026-02-23", 139, 11, 0),
        ("2026-02-25", 150, 0, 0),
    ]
    failing = [
        s for s in timeline if s["coalition"] + s["opposition"] + s["vacant"] != 150
    ]
    assert not failing, show_items(failing)


def test_a_vacant_seat_counts_for_its_faction() -> None:
    """The same changeover with the source's vacancies: the seats stay the faction's, so
    the coalition keeps its 150 and nothing is left unaccounted."""
    posts = [_post("d66", "2026-02-23")]
    seats = [_seat(f"m{n}", "d66", "2025-11-12") for n in range(139)]
    seats += [_seat(f"new{n}", "d66", "2026-02-25") for n in range(11)]
    vacancies = [
        {"faction_key": "d66", "from_date": "2026-02-23", "to_date": "2026-02-24"}
        for _ in range(11)
    ]
    timeline = seat_timeline(posts, seats, "2026-02-23", "2026-03-01", vacancies)
    # the seats no member held are vacant, the coalition's among them
    assert [
        (s["from_date"], s["coalition"], s["vacant"], s["coalition_vacant"])
        for s in timeline
    ] == [
        ("2026-02-23", 150, 11, 11),
        ("2026-02-25", 150, 0, 0),
    ]
    assert timeline[0]["factions"] == [
        {"key": "d66", "seats": 150, "vacant": 11, "coalition": True}
    ]


def test_a_member_who_moves_on_the_day_her_seat_ends_is_one_seat() -> None:
    """Agnes Joseph, NSC to BBB on 31 July 2025: the Kamer ends her NSC seat on the day her
    BBB seat begins. Read one faction a day, the Kamer holds 150 seats that day, not 151,
    and the change is an overstap (BBB held seats before)."""
    holdings: list[tuple[str, str, dict[str, str | None]]] = [
        ("joseph", "nsc", {"from_date": "2023-12-06", "to_date": "2025-07-31"})
    ]
    holdings += [("joseph", "bbb", {"from_date": "2025-07-31", "to_date": None})]
    holdings += [(f"nsc{n}", "nsc", {"from_date": "2023-12-06", "to_date": None})
                 for n in range(19)]  # fmt: skip
    holdings += [(f"bbb{n}", "bbb", {"from_date": "2023-12-06", "to_date": None})
                 for n in range(7)]  # fmt: skip
    holdings += [(f"opp{n}", "opp", {"from_date": "2023-12-06", "to_date": None})
                 for n in range(123)]  # fmt: skip
    seats = [
        _seat(person, faction, period["from_date"], period["to_date"])
        for person, faction, period in one_faction_at_a_time(holdings)
    ]
    posts = [_post(f, "2024-07-02") for f in ("vvd", "nsc", "bbb")]
    timeline = seat_timeline(posts, seats, "2025-07-30", "2025-08-01")
    assert [(s["from_date"], s["coalition"] + s["opposition"]) for s in timeline] == [
        ("2025-07-30", 150),
        ("2025-07-31", 150),
    ]
    assert seats_on(seats, "2025-07-31") == {"nsc": 19, "bbb": 8, "opp": 123}
    events = tk_events(
        "2025-07-31", seats, [], {"vvd", "nsc", "bbb"}, {"vvd", "nsc", "bbb"}
    )
    assert [(e["kind"], e["factions"], e["members"]) for e in events] == [
        ("overstap", ["bbb", "nsc"], ["joseph"])
    ]


def test_schoof_keeps_its_88_seats_on_its_first_day() -> None:
    """Kabinet-Schoof, 2 July 2024, as the source records it: 14 members became
    bewindspersonen, their seats vacant (FractieZetelVacature) until their successors took
    them on 4 July (PVV 4, VVD 4, NSC 4, BBB 2). Seated that day: PVV 33, VVD 20, NSC 16,
    BBB 5 (74); with the vacant seats the coalition holds its 88."""
    posts = [_post(f, "2024-07-02") for f in ("pvv", "vvd", "nsc", "bbb")]
    held = {"pvv": 33, "vvd": 20, "nsc": 16, "bbb": 5}
    vacant = {"pvv": 4, "vvd": 4, "nsc": 4, "bbb": 2}
    seats = [
        _seat(f"{f}{n}", f, "2023-12-06")
        for f, count in held.items()
        for n in range(count)
    ]
    seats += [
        _seat(f"{f}_new{n}", f, "2024-07-04")
        for f, count in vacant.items()
        for n in range(count)
    ]
    seats += [_seat(f"opp{n}", "opp", "2023-12-06") for n in range(62)]
    vacancies = [
        # TotEnMet 4 July, the day the successor takes the seat: vacant until the 3rd
        {"faction_key": f, "from_date": "2024-07-02", "to_date": "2024-07-03"}
        for f, count in vacant.items()
        for _ in range(count)
    ]
    timeline = seat_timeline(posts, seats, "2024-07-02", "2024-07-10", vacancies)
    first = timeline[0]
    assert (
        first["from_date"],
        first["coalition"],
        first["opposition"],
        first["vacant"],
        first["coalition_vacant"],
    ) == (
        "2024-07-02",
        88,
        62,
        14,
        14,
    )
    # the seats held: every seat but the vacant ones
    held_seats = sum(f["seats"] - f["vacant"] for f in first["factions"])
    assert held_seats == 150 - first["vacant"] == 136
    assert {f["key"]: (f["seats"], f["vacant"]) for f in first["factions"]} == {
        "pvv": (37, 4),
        "vvd": (24, 4),
        "nsc": (20, 4),
        "bbb": (7, 2),
        "opp": (62, 0),
    }
    # without the vacancies the coalition looks 14 seats short, as Front-end #1 saw
    assert seat_timeline(posts, seats, "2024-07-02", "2024-07-10")[0]["coalition"] == 74


def test_each_coalition_faction_with_its_choice_most_seats_first() -> None:
    votes = [("vvd", "Voor", 24), ("pvv", "Tegen", 37), ("gl", "Voor", 25)]
    votes += [("nsc", "Voor", 3), ("nsc", "Tegen", 2), ("bbb", "Niet deelgenomen", 7)]
    result = vote_pattern(votes, COALITION)
    assert result is not None
    assert result["factions"] == [
        {"key": "pvv", "choice": "Tegen", "seats_for": 0, "seats_against": 37},
        {"key": "vvd", "choice": "Voor", "seats_for": 24, "seats_against": 0},
        # a roll call whose members went both ways: no one choice
        {"key": "nsc", "choice": None, "seats_for": 3, "seats_against": 2},
    ]


# ── The cabinet and coalition of a vote (``semantic tk-coalition-votes``) ───


def _cabinet(key: str, start: str, end: str | None, faction: str) -> dict:
    return {
        "key": key,
        "from_date": start,
        "to_date": end,
        "posts": [_post(faction, start, end)],
    }


# Rutte IV hands over to Schoof on 2 July 2024; oldest first, whatever the query sorts
HANDOVER = [
    _cabinet("rutte_iv", "2022-01-10", "2024-07-02", "d66"),
    _cabinet("schoof", "2024-07-02", None, "pvv"),
]


def _vote(day: str, voter: str, choice: str, seats: int = 0) -> dict:
    return {
        "date": day,
        "voter_collection": "factions",
        "voter": voter,
        "choice": choice,
        "seats": seats,
    }


def test_a_vote_on_the_handover_day_is_one_of_the_new_cabinet() -> None:
    votes = [
        _vote("2024-07-02", "pvv", "Voor", 37),
        _vote("2024-07-02", "d66", "Tegen", 9),
    ]
    row = _decision_row("d1", votes, HANDOVER, {})
    assert row is not None
    assert row["cabinet"] == "schoof"
    assert [f["key"] for f in row["factions"]] == ["pvv"]
    # the day before, the old one
    before = [
        _vote("2024-07-01", "pvv", "Voor", 17),
        _vote("2024-07-01", "d66", "Tegen", 24),
    ]
    assert (_decision_row("d0", before, HANDOVER, {}) or {})["cabinet"] == "rutte_iv"


def test_a_member_votes_with_the_faction_they_sat_in_that_day() -> None:
    member = {
        "date": "2024-07-02",
        "voter_collection": "members",
        "voter": "m1",
        "choice": "Voor",
        "seats": None,
    }
    factions_of: dict[str, list[dict[str, Any]]] = {
        "m1": [
            {"faction_key": "d66", "from_date": "2021-03-31", "to_date": "2024-07-01"},
            {"faction_key": "pvv", "from_date": "2024-07-02", "to_date": None},
        ]
    }
    row = _decision_row("d1", [member], HANDOVER, factions_of)
    assert row is not None
    assert row["factions"] == [
        {"key": "pvv", "choice": "Voor", "seats_for": 1, "seats_against": 0}
    ]


def test_votes_are_grouped_per_decision_only_when_sorted_by_it() -> None:
    rows = [{"id": "a"}, {"id": "a"}, {"id": "b"}]
    assert [(key, len(group)) for key, group in _per_decision(rows)] == [
        ("a", 2),
        ("b", 1),
    ]
    with pytest.raises(ValueError, match="sorted"):
        list(_per_decision([{"id": "a"}, {"id": "b"}, {"id": "a"}]))
