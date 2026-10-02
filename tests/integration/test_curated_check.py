"""The curated seating plan against the database: a faction with seats the plan does not
place, or with another number of seats than on the plan, is a problem of ``lawgraph check``
(in the small database: NSC, whose seats were of before the plan), and a faction whose
number of seats differs from the plan's."""

from __future__ import annotations

from lawgraph.commands.curated import database_notes, database_problems
from lawgraph.config.constants import COLLECTION_FACTIONS, COLLECTION_INSTRUMENTS
from lawgraph.core.models import Node, NodeType
from lawgraph.db import GraphStore, NodeWriter


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
    store = GraphStore()
    with NodeWriter(store) as writer:
        writer.add_all(
            [
                _faction("sp", "SP", 3),
                _faction("nieuw_sociaal_contract", "NSC", 19),
                _faction("kvp", "KVP", 0),  # not seated: needs no place
            ]
        )
    problems = [p for p in database_problems(store) if p.startswith("seating:")]
    assert len(problems) == 1
    assert problems[0].startswith("seating: nieuw_sociaal_contract (NSC) has seats")
    # the listed keys no faction here has are notes, not problems: a partial database
    notes = database_notes(store)
    assert "seating: vvd: no faction in the database has this key" in notes
    assert not any(":sp:" in n.replace(" ", "") for n in notes)


def test_a_number_of_seats_other_than_the_plans_is_a_problem_a_new_member_a_note(
    database: str,
) -> None:
    store = GraphStore()
    with NodeWriter(store) as writer:
        writer.add_all(
            [
                # as on the plan; a seat changed after it (a new member): only a note
                _faction("vvd", "VVD", 22, "2026-09-02"),
                # one seat more than on the plan: the seating has changed
                _faction("pvv", "PVV", 20, "2026-07-15"),
            ]
        )
    assert [p for p in database_problems(store) if p.startswith("seating:")] == [
        "seating: pvv (PVV) has 20 seats, the plan 19: take the new plan of the Tweede "
        "Kamer (wie zit waar)"
    ]
    assert (
        "seating: a seat changed on 2026-09-02, after the plan of 2026-06-01 (the seating "
        "changes only when the numbers of seats do)"
    ) in database_notes(store)


def test_an_abbreviation_of_an_instrument_the_graph_lacks_is_a_problem(
    database: str,
) -> None:
    store = GraphStore()
    # the First Protocol to the ECHR is in the graph: only the AVG's law is missing
    with NodeWriter(store) as writer:
        writer.add(
            Node(
                collection=COLLECTION_INSTRUMENTS,
                type=NodeType.INSTRUMENT,
                key="bwbv0001001",
                props={"bwb_id": "BWBV0001001", "title": "Protocol bij het EVRM"},
            )
        )
    assert database_problems(store) == [
        "instrument-abbreviations: 32016R0679 (AVG): no instrument in the graph has "
        "this id"
    ]
    with NodeWriter(store) as writer:
        writer.add(
            Node(
                collection=COLLECTION_INSTRUMENTS,
                type=NodeType.INSTRUMENT,
                key="32016r0679",
                props={"celex": "32016R0679", "title": "Verordening (EU) 2016/679"},
            )
        )
    assert database_problems(store) == []
