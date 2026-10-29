"""The full search ends within one deadline for all its types, not one per type."""

from __future__ import annotations

import time

import pytest

from lawgraph.db.queries.search import dispatch


def test_a_type_that_started_late_has_what_is_left_of_the_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dispatch, "FULL_BUDGET", 2.0)
    monkeypatch.setattr(dispatch, "FALLBACK_BUDGET", 0.5)
    seen: list[float] = []

    def spy(search, budget=None):
        seen.append(round(budget, 1))
        return [], True

    monkeypatch.setattr(dispatch, "_within_budget", spy)
    now = time.monotonic()
    dispatch._full_or_live(
        list, list, now + 2.5
    )  # started with the whole deadline left
    dispatch._full_or_live(list, list, now + 1.0)  # waited 1.5 s for a thread
    dispatch._full_or_live(list, list, now + 0.2)  # waited past it: live alone
    assert seen == [2.0, 0.5, 0.5, 0.5, 0.0, 0.5]


def test_the_deadline_is_the_two_budgets_together(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dispatch, "FULL_BUDGET", 2.0)
    monkeypatch.setattr(dispatch, "FALLBACK_BUDGET", 0.5)
    assert dispatch.full_deadline() - time.monotonic() == pytest.approx(2.5, abs=0.1)
