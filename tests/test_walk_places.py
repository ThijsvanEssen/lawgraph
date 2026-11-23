"""Walks past the first level run ``WALKS.n`` at a time: one more waits ``WALKS.wait`` for a
place and then answers 503 (``ReadTimedOut``), so slow walks never hold every connection of
the requests. A walk of one level needs no place."""

from __future__ import annotations

import contextlib

import pytest

from lawgraph.db.queries.nodes import WALKS
from lawgraph.db.request_context import ReadTimedOut


def test_a_walk_past_the_places_answers_503_and_one_level_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(WALKS, "wait", 0.01)
    with contextlib.ExitStack() as running:
        for _ in range(WALKS.n):
            running.enter_context(WALKS.held())
        with pytest.raises(ReadTimedOut), WALKS.held():
            pass
        with WALKS.held(needs=False):
            pass
    with WALKS.held():  # the places are free again
        pass
