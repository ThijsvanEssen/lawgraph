"""An office over the renames of its ministry, and the seat something is attributed to."""

from __future__ import annotations

from typing import Any

from lawgraph.core.seats import (
    base_seat,
    family,
    is_of_kind,
    merged_from,
    merged_into,
    ministries_of,
    seat_acted_from,
)


def _post(seat: str, function: str, ministry: str | None, **dates: Any) -> dict:
    return {"seat": seat, "function": function, "ministry": ministry, **dates}


MINISTER_BZ = _post(
    "bz/minister", "minister van Buitenlandse Zaken", "bz", from_date="2025-01-01"
)
MINISTER_AENM = _post(
    "aenm/minister", "minister van Asiel en Migratie", "aenm", from_date="2025-06-01"
)
SECRETARY = _post(
    "fin/staatssecretaris#2",
    "staatssecretaris van Financiën",
    "fin",
    from_date="2024-01-01",
    to_date="2024-12-31",
)


def test_a_seat_keeps_its_portfolio_over_the_renames_of_its_ministry() -> None:
    assert family("ienw/minister") == ["ienm/minister", "ienw/minister"]
    assert family("venj/staatssecretaris/rechtsbescherming") == [
        "jenv/staatssecretaris/rechtsbescherming",
        "justitie/staatssecretaris/rechtsbescherming",
        "venj/staatssecretaris/rechtsbescherming",
    ]
    assert ministries_of("jenv/minister") == ["jenv", "justitie", "venj"]


def test_a_name_that_came_back_is_one_family() -> None:
    assert family("ez/minister") == [
        "eli/minister",
        "ez/minister",
        "ezk/minister",
        "hn/minister",
    ]


def test_a_merger_is_no_rename() -> None:
    assert "venw/minister" not in family("ienw/minister")
    assert merged_from("ienw/minister") == ["venw/minister", "vrom/minister"]
    assert merged_into("venw/minister") == ["ienm/minister"]
    # lnv merged into eli and came back later, without a succession: a line of its own
    assert "eli/minister" not in family("lnv/minister")
    assert merged_from("ez/minister") == ["lnv/minister"]
    assert merged_into("lnv/minister") == ["eli/minister"]
    assert merged_into("ez/minister") == []


def test_lanes_are_one_seat_and_a_seat_without_a_ministry_has_no_family() -> None:
    assert base_seat("bz/staatssecretaris#2") == "bz/staatssecretaris"
    assert family("bz/staatssecretaris#2") == ["bz/staatssecretaris"]
    assert family("-/minister/immigratie-en-asiel") == [
        "-/minister/immigratie-en-asiel"
    ]
    assert ministries_of("-/minister/immigratie-en-asiel") == []
    assert family("viceminister-president") == ["viceminister-president"]
    assert merged_from("viceminister-president") == []


def _seat(
    posts: list[dict], day: str | None, function: str, ministry: str | None
) -> Any:
    return seat_acted_from(posts, day=day, function=function, ministry=ministry)


def test_the_post_held_that_day_whatever_the_ministry_of_the_commitment() -> None:
    # filed under Justitie en Veiligheid by a minister of Asiel en Migratie alone
    assert (
        _seat(
            [MINISTER_AENM], "2025-07-01", "Minister van Justitie en Veiligheid", "jenv"
        )
        == "aenm/minister"
    )


def test_two_seats_that_day_the_ministry_decides_or_it_is_neither() -> None:
    posts = [MINISTER_BZ, MINISTER_AENM]
    assert _seat(posts, "2025-03-01", "Minister", None) == "bz/minister"
    assert _seat(posts, "2025-07-01", "Minister", "aenm") == "aenm/minister"
    assert _seat(posts, "2025-07-01", "Minister", "jenv") is None
    assert _seat(posts, "2025-07-01", "Minister", None) is None


def test_the_kind_and_the_day_of_the_post() -> None:
    assert _seat([SECRETARY], "2024-06-01", "Minister van Financiën", "fin") is None
    function = "Staatssecretaris van Financiën"
    assert _seat([SECRETARY], "2024-06-01", function, "fin") == "fin/staatssecretaris"
    # a letter sent just after the post ended still belongs to it
    assert _seat([SECRETARY], "2025-01-14", function, "fin") == "fin/staatssecretaris"
    assert _seat([SECRETARY], "2025-01-15", function, "fin") is None
    assert _seat([SECRETARY], None, function, "fin") is None


def test_the_deputy_seat_gets_nothing() -> None:
    deputy = _post(
        "viceminister-president", "viceminister-president", None, from_date="2025-01-01"
    )
    assert _seat([deputy, MINISTER_BZ], "2025-03-01", "Minister", None) == "bz/minister"
    assert _seat([deputy], "2025-03-01", "Minister", None) is None


def test_two_names_of_one_office_are_one_seat() -> None:
    posts = [
        _post("eli/minister", "minister", "eli", from_date="2012-01-01"),
        _post("ez/minister", "minister", "ez", from_date="2012-12-20"),
    ]
    assert _seat(posts, "2012-12-25", "Minister", None) == "eli/minister"


def test_the_kind_of_a_seat() -> None:
    assert is_of_kind("fin/staatssecretaris#2", "Staatssecretaris van Financiën")
    assert is_of_kind("-/minister_zonder_portefeuille/medische-zorg", "Minister voor X")
    assert not is_of_kind("fin/minister", "Staatssecretaris van Financiën")
