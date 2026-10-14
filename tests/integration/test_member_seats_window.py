"""A seat the Kamer records later, for a member and a faction stored before: ``normalize
tk-dossiers --since`` reads only the new seat record, and still makes the member's MEMBER_OF
edge to that faction (the member and the faction come from the database, not from the
window)."""

from __future__ import annotations

import datetime as dt
from typing import Any

from lawgraph.config.constants import (
    RAW_KIND_TK_FRACTIE,
    RAW_KIND_TK_FRACTIEZETELPERSOON,
    RAW_KIND_TK_PERSOON,
)
from lawgraph.db import GraphStore
from tests.integration.seed import tk_faction, tk_person, tk_seat, uid, write_tk

VVD, PRO = uid(1, 8), uid(3, 8)
KLAVER = uid(4, 9)


def _member_of(store: GraphStore) -> set[tuple[str, str]]:
    return {
        (row["from_id"], row["to_id"])
        for row in store.query(
            "SELECT from_id, to_id FROM edges WHERE relation = 'MEMBER_OF'"
            " AND to_collection = 'factions'"
        )
    }


def test_a_new_seat_of_a_stored_member_is_linked_in_a_window(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    write_tk(
        store,
        [
            (RAW_KIND_TK_FRACTIE, tk_faction(VVD, "VVD", "1948-01-23", None, 22)),
            (RAW_KIND_TK_FRACTIE, tk_faction(PRO, "PRO", "2026-06-09", None, 20)),
            (RAW_KIND_TK_PERSOON, tk_person(KLAVER, "Jesse", "Klaver")),
            (
                RAW_KIND_TK_FRACTIEZETELPERSOON,
                tk_seat(10, KLAVER, VVD, "2020-01-01", "2026-06-08"),
            ),
        ],
    )
    cli("normalize", "tk-dossiers")
    before = _member_of(store)
    assert len(before) == 1

    since = dt.datetime.now(dt.timezone.utc).isoformat()
    # the next day: the Kamer records his seat in PRO; his record and PRO's do not change
    write_tk(
        store,
        [
            (
                RAW_KIND_TK_FRACTIEZETELPERSOON,
                tk_seat(11, KLAVER, PRO, "2026-06-09", None),
            )
        ],
    )
    cli("normalize", "tk-dossiers", "--since", since)

    member = "members/" + KLAVER.lower().replace("-", "_")
    assert (member, "factions/pro") in _member_of(store)


def test_the_timeline_keeps_the_seats_before_the_window(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    write_tk(
        store,
        [
            (RAW_KIND_TK_FRACTIE, tk_faction(VVD, "VVD", "1948-01-23", None, 22)),
            (RAW_KIND_TK_FRACTIE, tk_faction(PRO, "PRO", "2026-06-09", None, 20)),
            (RAW_KIND_TK_PERSOON, tk_person(KLAVER, "Jesse", "Klaver")),
            (
                RAW_KIND_TK_FRACTIEZETELPERSOON,
                tk_seat(10, KLAVER, VVD, "2020-01-01", "2026-06-08"),
            ),
        ],
    )
    cli("normalize", "tk-dossiers")
    since = dt.datetime.now(dt.timezone.utc).isoformat()
    write_tk(
        store,
        [
            (
                RAW_KIND_TK_FRACTIEZETELPERSOON,
                tk_seat(11, KLAVER, PRO, "2026-06-09", None),
            )
        ],
    )
    cli("normalize", "tk-dossiers", "--since", since)

    (row,) = store.query(
        "SELECT props -> 'faction_memberships' AS timeline, props ->> 'party' AS party"
        " FROM members"
    )
    assert [m["abbreviation"] for m in row["timeline"]] == ["VVD", "PRO"]
    assert row["party"] == "PRO"


def test_the_seats_again_link_every_stored_seat(database: str, cli: Any) -> None:
    """``normalize tk-dossiers --seats``: every stored seat linked again, read as the seat
    periods are read now; a seat ending on the day the next one, in another faction,
    begins (Agnes Joseph, NSC to BBB on 31 July 2025) ends the day before."""
    store = GraphStore()
    write_tk(
        store,
        [
            (RAW_KIND_TK_FRACTIE, tk_faction(VVD, "VVD", "1948-01-23", None, 22)),
            (RAW_KIND_TK_FRACTIE, tk_faction(PRO, "PRO", "2023-12-06", None, 20)),
            (RAW_KIND_TK_PERSOON, tk_person(KLAVER, "Agnes", "Joseph")),
        ],
    )
    cli("normalize", "tk-dossiers")
    assert _member_of(store) == set()
    # seats stored without a run that links them (as a run before this reading left them)
    write_tk(
        store,
        [
            (
                RAW_KIND_TK_FRACTIEZETELPERSOON,
                tk_seat(10, KLAVER, VVD, "2023-12-06", "2025-07-31"),
            ),
            (
                RAW_KIND_TK_FRACTIEZETELPERSOON,
                tk_seat(11, KLAVER, PRO, "2025-07-31", None),
            ),
        ],
    )
    cli("normalize", "tk-dossiers", "--seats")

    member = "members/" + KLAVER.lower().replace("-", "_")
    assert _member_of(store) == {(member, "factions/vvd"), (member, "factions/pro")}
    (row,) = store.query(
        "SELECT props -> 'faction_memberships' AS timeline, props ->> 'party' AS party"
        " FROM members"
    )
    periods = [
        (m["abbreviation"], m["from_date"], m["to_date"]) for m in row["timeline"]
    ]
    assert periods == [
        ("VVD", "2023-12-06", "2025-07-30"),
        ("PRO", "2025-07-31", None),
    ]
    assert row["party"] == "PRO"
