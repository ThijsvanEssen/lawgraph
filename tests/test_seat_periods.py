"""Seat periods read so they hold together (``core.seat_periods``)."""

from lawgraph.core.seat_periods import (
    mend_reversed_ends,
    seated_bounds,
    split_overlapping_chairs,
)


def _p(start: str, end: str | None, role: str = "Lid") -> dict:
    return {"from_date": start, "to_date": end, "role": role}


def test_an_end_before_the_start_is_read_from_the_next_seat() -> None:
    first, typo, last = (
        _p("2003-01-30", "2003-05-26"),
        _p("2006-11-30", "2003-02-22"),
        _p("2007-02-23", "2003-02-22"),
    )
    mended = mend_reversed_ends(
        [("kamp", "vvd", first), ("kamp", "vvd", typo), ("kamp", "vvd", last)]
    )
    assert [p for _, _, p in mended] == [first, _p("2006-11-30", "2007-02-22")]


def test_a_chair_chairs_until_the_next_one_does() -> None:
    held = split_overlapping_chairs(
        [
            ("rutte", "vvd", _p("2006-06-28", "2010-10-13", "Fractievoorzitter")),
            ("blok", "vvd", _p("2010-10-08", "2012-09-12", "Fractievoorzitter")),
            ("zijlstra", "vvd", _p("2010-10-08", None)),
        ]
    )
    assert held == [
        ("rutte", "vvd", _p("2006-06-28", "2010-10-07", "Fractievoorzitter")),
        ("rutte", "vvd", _p("2010-10-08", "2010-10-13")),
        ("blok", "vvd", _p("2010-10-08", "2012-09-12", "Fractievoorzitter")),
        ("zijlstra", "vvd", _p("2010-10-08", None)),
    ]


def test_a_handover_on_one_day_is_no_overlap_left() -> None:
    held = split_overlapping_chairs(
        [
            ("a", "nsc", _p("2025-04-19", "2025-09-02", "Fractievoorzitter")),
            ("b", "nsc", _p("2025-09-02", "2025-11-11", "Fractievoorzitter")),
        ]
    )
    assert held[0][2]["to_date"] == "2025-09-01"
    assert held[1] == ("a", "nsc", _p("2025-09-02", "2025-09-02"))


def test_a_faction_is_active_while_its_seats_are_held() -> None:
    seats = [_p("2023-10-27", "2026-06-09"), _p("2023-12-06", "2026-06-09")]
    assert seated_bounds("2023-10-27", "2026-06-10", seats) == (
        "2023-10-27",
        "2026-06-09",
    )
    assert seated_bounds("2026-06-09", None, [_p("2026-06-10", None)]) == (
        "2026-06-10",
        None,
    )
    # an open seat keeps an ended record's end; no seats keep the record's dates
    assert (
        seated_bounds("2023-10-27", "2026-06-10", [_p("2023-10-27", None)])[1]
        == "2026-06-10"
    )
    assert seated_bounds("2023-10-27", "2026-06-10", []) == ("2023-10-27", "2026-06-10")


def test_seats_before_2006_do_not_date_a_faction() -> None:
    # the Kamer keeps the seats of only some members before 30 November 2006
    assert seated_bounds(
        "1990-11-24", "2023-10-26", [_p("1993-04-21", "2003-01-29")]
    ) == (
        "1990-11-24",
        "2023-10-26",
    )
