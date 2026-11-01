"""The parts of the warm-up: one name each (what is kept of a part is kept by its name), and
the tables of a part kept per table are tables of the database."""

from __future__ import annotations

import pytest

from lawgraph.api import warm
from lawgraph.db import version_cache
from lawgraph.db.schema import NODE_COLLECTIONS, SEARCH_FIELDS


def test_every_part_has_its_own_name() -> None:
    names = [part.name for part in (*warm.PARTS, *warm.TAIL)]
    assert len(names) == len(set(names))


def test_the_tables_of_a_part_are_tables_of_the_database() -> None:
    known = {*NODE_COLLECTIONS, *SEARCH_FIELDS, "edges"}
    for part in (*warm.PARTS, *warm.TAIL):
        if part.tables is not None:
            assert part.tables and set(part.tables) <= known, part.name


def test_the_first_warm_up_goes_on_while_the_data_moves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """During a run the data never stands still: without this, an API started then has no
    earlier answer to give for as long as the run lasts. A later warm-up stops."""

    class Moving:
        name = "moving"

        def __init__(self) -> None:
            self.reads = 0

        def data_version(self, tables: object = None) -> str:
            self.reads += 1
            return str(self.reads)

    ran: list[str] = []
    parts = tuple(
        warm.Part(name, lambda _store, name=name: ran.append(name))
        for name in ("a", "b")
    )
    monkeypatch.setattr(warm, "_warmed", None)
    assert warm._warm_lane(Moving(), "0", parts)  # type: ignore[arg-type]
    assert ran == ["a", "b"]

    monkeypatch.setattr(warm, "_warmed", "0")
    ran.clear()
    assert not warm._warm_lane(Moving(), "0", parts)  # type: ignore[arg-type]
    assert ran == []
    assert version_cache.superseded(Moving(), "0")
