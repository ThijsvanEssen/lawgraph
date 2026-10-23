"""Which faction took over another, read from the seats alone (``core.faction_succession``)."""

from __future__ import annotations

from lawgraph.core.faction_succession import Holding, Succession, successions


def _h(person: str, faction: str, start: str, end: str | None) -> Holding:
    return Holding(person, faction, start, end)


def test_all_seats_passing_the_next_day_to_a_new_faction_make_it_the_successor() -> (
    None
):
    """GroenLinks-PvdA ended 9 June 2026 and PRO began on the 10th; one member left the Kamer
    that day and her seat is filled in PRO."""
    held = [
        _h("a", "gl_pvda", "2023-10-27", "2026-06-09"),
        _h("b", "gl_pvda", "2023-10-27", "2026-06-09"),
        _h("c", "gl_pvda", "2023-12-06", "2026-06-09"),  # leaves the Kamer
        _h("a", "pro", "2026-06-10", None),
        _h("b", "pro", "2026-06-10", None),
        _h("d", "pro", "2026-06-10", None),  # fills her seat
    ]
    assert successions(held) == [Succession("gl_pvda", "pro", "2026-06-10", 2)]


def test_two_factions_that_merge_are_both_predecessors() -> None:
    held = [
        _h("a", "pvda", "2020-01-01", "2023-10-26"),
        _h("b", "gl", "2020-01-01", "2023-10-26"),
        _h("a", "gl_pvda", "2023-10-27", None),
        _h("b", "gl_pvda", "2023-10-27", None),
    ]
    assert [(s.predecessor, s.successor) for s in successions(held)] == [
        ("gl", "gl_pvda"),
        ("pvda", "gl_pvda"),
    ]


def test_a_gap_is_not_filled() -> None:
    held = [
        _h("a", "old", "2020-01-01", "2023-10-26"),
        _h("a", "new", "2023-10-28", None),  # a day without a seat
    ]
    assert successions(held) == []


def test_seats_that_go_to_two_factions_pass_to_none() -> None:
    held = [
        _h("a", "old", "2020-01-01", "2021-03-30"),
        _h("b", "old", "2020-01-01", "2021-03-30"),
        _h("a", "x", "2021-03-31", None),
        _h("b", "y", "2021-03-31", None),
    ]
    assert successions(held) == []


def test_a_faction_that_is_already_there_is_joined_not_continued() -> None:
    held = [
        _h("a", "old", "2020-01-01", "2021-03-30"),
        _h("z", "there", "2010-01-01", None),
        _h("a", "there", "2021-03-31", None),
    ]
    assert successions(held) == []


def test_a_seat_lost_on_the_way_is_no_succession() -> None:
    """Five seats, one member sits on in a new faction: the other four seats do not pass."""
    held = [_h(p, "old", "2020-01-01", "2021-03-30") for p in "abcde"]
    held.append(_h("a", "new", "2021-03-31", None))
    assert successions(held) == []


def test_a_faction_with_a_seat_left_has_no_successor() -> None:
    held = [
        _h("a", "old", "2020-01-01", None),
        _h("b", "old", "2020-01-01", "2021-03-30"),
        _h("b", "new", "2021-03-31", None),
    ]
    assert successions(held) == []
