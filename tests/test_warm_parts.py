"""The parts of the warm-up: one name each (what is kept of a part is kept by its name), and
the tables of a part kept per table are tables of the database."""

from __future__ import annotations

from lawgraph.api import warm
from lawgraph.db.schema import NODE_COLLECTIONS, SEARCH_FIELDS


def test_every_part_has_its_own_name() -> None:
    names = [part.name for part in (*warm.PARTS, *warm.TAIL)]
    assert len(names) == len(set(names))


def test_the_tables_of_a_part_are_tables_of_the_database() -> None:
    known = {*NODE_COLLECTIONS, *SEARCH_FIELDS, "edges"}
    for part in (*warm.PARTS, *warm.TAIL):
        if part.tables is not None:
            assert part.tables and set(part.tables) <= known, part.name
