"""The curated seating plan against the database: a faction with seats the plan does not
place, or a plan older than the last change of a seat, is a problem of ``lawgraph check``
(in the small database: NSC, whose seats are of before the plan)."""

from __future__ import annotations

from lawgraph.commands.curated import database_notes, database_problems
from lawgraph.config.constants import COLLECTION_FACTIONS
from lawgraph.core.models import Node, NodeType
from lawgraph.db import ArangoStore, NodeWriter


def _faction(
    key: str, abbreviation: str, seats: int, changed: str | None = None
) -> Node:
    return Node(
        collection=COLLECTION_FACTIONS,
        type=NodeType.FACTION,
        key=key,
        labels=["TK"],
        props={
            "name": abbreviation,
            "abbreviation": abbreviation,
            "seats": seats,
            "active": seats > 0,
            "seats_changed_on": changed,
        },
    )


def test_a_seated_faction_without_a_place_is_a_problem(database: str) -> None:
    store = ArangoStore()
    with NodeWriter(store) as writer:
        writer.add_all(
            [
                _faction("sp", "SP", 3),
                _faction("nieuw_sociaal_contract", "NSC", 19),
                _faction("kvp", "KVP", 0),  # not seated: needs no place
            ]
        )
    problems = database_problems(store)
    assert len(problems) == 1
    assert problems[0].startswith("seating: nieuw_sociaal_contract (NSC) has seats")
    # the listed keys no faction here has are notes, not problems: a partial database
    notes = database_notes(store)
    assert "seating: vvd: no faction in the database has this key" in notes
    assert not any(":sp:" in n.replace(" ", "") for n in notes)


def test_a_plan_older_than_a_seat_change_is_a_problem(database: str) -> None:
    store = ArangoStore()
    with NodeWriter(store) as writer:
        writer.add_all(
            [
                _faction("sp", "SP", 3, "2026-05-01"),
                _faction("pvv", "PVV", 19, "2026-07-15"),
            ]
        )
    assert database_problems(store) == [
        "seating: the plan is of 2026-06-01, a seat changed on 2026-07-15: take the new "
        "plan of the Tweede Kamer (wie zit waar)"
    ]
