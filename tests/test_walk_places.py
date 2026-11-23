"""Walks past the first level run ``WALKS`` at a time: one more waits ``WALK_WAIT`` for a
place and then answers 503 (``ReadTimedOut``), so slow walks never hold every connection of
the requests. A walk of one level needs no place."""

from __future__ import annotations

import contextlib

import pytest

from lawgraph.db.queries import nodes
from lawgraph.db.request_context import ReadTimedOut


def test_a_walk_past_the_places_answers_503_and_one_level_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(nodes, "WALK_WAIT", 0.01)
    with contextlib.ExitStack() as running:
        for _ in range(nodes.WALKS):
            running.enter_context(nodes._walk_place(3))
        with pytest.raises(ReadTimedOut), nodes._walk_place(2):
            pass
        with nodes._walk_place(1):
            pass
    with nodes._walk_place(3):  # the places are free again
        pass
