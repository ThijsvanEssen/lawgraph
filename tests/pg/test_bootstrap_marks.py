"""The marks of ``lawgraph bootstrap`` in ``pipeline_state`` on a real PostgreSQL."""

from __future__ import annotations

from lawgraph.commands import bootstrap_plan as bp
from lawgraph.db import GraphStore
from lawgraph.db.queries import state as state_queries

CODE = bp.Code("0.78.3", "build-0.78.3-12-g142ffed", "142ffed")


def test_a_step_is_marked_read_back_and_unmarked(store: GraphStore) -> None:
    assert bp.marks(store) == {}
    bp.mark_done(store, "normalize tk", 12.34, CODE)
    bp.mark_done(store, "retrieve tk-content", 3600, bp.Code(None, None, None))
    state_queries.set_covered_until(store, "normalize", "2026-10-06T00:00:00+00:00")

    marks = bp.marks(store)
    assert set(marks) == {"normalize tk", "retrieve tk-content"}  # not the phase marks
    assert marks["normalize tk"].code == CODE
    assert marks["normalize tk"].seconds == 12.3
    assert marks["retrieve tk-content"].code == bp.Code(None, None, None)

    bp.unmark(store, "normalize tk")
    assert set(bp.marks(store)) == {"retrieve tk-content"}


def test_states_starting_with_is_by_prefix_only(store: GraphStore) -> None:
    state_queries.set_state(store, "bootstrap a", {"x": 1})
    state_queries.set_state(store, "retrieve eerstekamer-agenda", {"y": 2})
    assert state_queries.states_starting_with(store, "bootstrap ") == {
        "bootstrap a": {"x": 1}
    }
