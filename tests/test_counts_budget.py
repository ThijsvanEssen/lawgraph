"""The counts beside the page of a list (``page_with_counts``): the page comes whole at
once, the counts within ``COUNTS_BUDGET`` of the start of the answer or ``total`` null,
empty facets and ``partial``, and the next request, with the counts kept, has them."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from typing import Any, cast

import pytest

from lawgraph.db import GraphStore, request_context
from lawgraph.db.queries import _helpers, decisions, documents, instruments, judgments
from lawgraph.db.queries import feed as feed_queries
from lawgraph.db.queries.decisions import DecisionFilters
from lawgraph.db.queries.feed_sql import FeedFilters
from lawgraph.db.request_context import ReadTimedOut
from tests.fakes import InMemoryStore

COUNTED = {"total": 7, "facets": {"kind": [1]}}


@pytest.fixture(autouse=True)
def _a_request(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(request_context, "READ_TIMEOUT_MS", 600_000)
    token = request_context.set_read_deadline(30.0)
    try:
        yield
    finally:
        request_context.reset_read_deadline(token)


class Counting:
    """A count that is not kept yet while the budget is 0, and kept after."""

    def __init__(self, value: Any = COUNTED) -> None:
        self.value = value

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        left = request_context.read_time_left()
        if left is not None and left < 0.05:
            raise ReadTimedOut("not counted yet")
        return self.value


def test_the_counts_come_with_the_page() -> None:
    page, counted = _helpers.page_with_counts(lambda: ["a"], lambda: COUNTED, "x")
    assert (page, counted) == (["a"], COUNTED)
    assert _helpers.with_counts(page, counted) == {"items": ["a"], **COUNTED}


def test_counts_past_the_budget_are_none_and_the_page_whole() -> None:
    def counts() -> dict[str, Any]:
        raise ReadTimedOut("slow")

    page, counted = _helpers.page_with_counts(lambda: ["a"], counts, "x")
    assert counted is None
    assert _helpers.with_counts(page, counted, {"kind": []}) == {
        "items": ["a"],
        "total": None,
        "facets": {"kind": []},
        "partial": True,
    }


def test_the_time_of_the_page_is_part_of_the_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_helpers, "COUNTS_BUDGET", 0.2)
    seen: list[float] = []

    def slow_page() -> list[str]:
        time.sleep(0.25)
        return ["a"]

    def counts() -> dict[str, Any]:
        seen.append(request_context.read_time_left() or 0.0)
        return COUNTED

    _helpers.page_with_counts(slow_page, counts, "x")
    assert seen == [0.0]


def test_a_cancelled_client_is_not_a_budget() -> None:
    def counts() -> dict[str, Any]:
        raise request_context.RequestCancelled("gone")

    with pytest.raises(request_context.RequestCancelled):
        _helpers.page_with_counts(lambda: [], counts, "x")


def _both_requests(
    monkeypatch: pytest.MonkeyPatch, ask: Callable[[], dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The answer with a budget of 0 and then with the real one."""
    monkeypatch.setattr(_helpers, "COUNTS_BUDGET", 0.0)
    first = ask()
    monkeypatch.setattr(_helpers, "COUNTS_BUDGET", 3.0)
    return first, ask()


def test_decisions_partial_then_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(decisions, "_page", lambda *a: [])
    monkeypatch.setattr(decisions, "_add_motions", lambda *a: None)
    monkeypatch.setattr(decisions, "decision_counts", Counting())
    store = cast(GraphStore, InMemoryStore())
    first, second = _both_requests(
        monkeypatch, lambda: decisions.get_decisions(store, DecisionFilters())
    )
    assert first["partial"] is True and first["total"] is None
    assert first["facets"] == decisions.EMPTY_FACETS
    assert second["total"] == 7 and "partial" not in second


def test_feed_partial_then_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feed_queries, "_page_items", lambda *a: ([], None))
    monkeypatch.setattr(feed_queries, "_counts_of_events", Counting())
    store = cast(GraphStore, object())
    first, second = _both_requests(
        monkeypatch, lambda: feed_queries.get_feed(store, FeedFilters())
    )
    assert first["partial"] is True
    assert (first["total"], first["facets"]) == (None, None)
    assert second["total"] == 7 and "partial" not in second


def test_judgments_partial_then_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(judgments, "_page", lambda *a, **k: [])
    monkeypatch.setattr(judgments, "_total", Counting(7))
    monkeypatch.setattr(judgments, "lasting_rows", Counting([]))
    monkeypatch.setattr(judgments, "_with_narrower", lambda tree, rows: tree)
    store = cast(GraphStore, object())
    first, second = _both_requests(
        monkeypatch, lambda: judgments.get_judgments_list(store)
    )
    assert first["partial"] is True and first["total"] is None
    assert first["facets"] is None
    assert second["total"] == 7 and "partial" not in second
    assert set(second["facets"]) == set(judgments._FACETS)


def test_instruments_partial_then_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(instruments, "_listed", lambda *a: ([], None))
    count = Counting()

    def rows(store: Any, sql: Any, *a: Any, **k: Any) -> list[Any]:
        count()
        return [0] if "AS total" in str(sql) else []

    monkeypatch.setattr(instruments, "cached_rows", rows)
    monkeypatch.setattr(instruments, "_legal_area_tree", lambda rows: [])
    store = cast(GraphStore, object())
    first, second = _both_requests(
        monkeypatch, lambda: instruments.get_instruments_list(store)
    )
    assert first["partial"] is True and first["total"] is None
    assert second["total"] == 0 and "partial" not in second
    assert second["facets"] is not None


@pytest.mark.parametrize("facets", [False, True])
def test_instruments_counts_of_a_search_are_computed_inline(
    monkeypatch: pytest.MonkeyPatch, facets: bool
) -> None:
    monkeypatch.setattr(instruments, "_listed", lambda *a: ([], None))
    monkeypatch.setattr(instruments, "_legal_area_tree", lambda rows: [])
    inline: list[bool] = []

    def rows(store: Any, sql: Any, *a: Any, **k: Any) -> list[Any]:
        inline.append(k["inline"])
        return [0] if "AS total" in str(sql) else []

    monkeypatch.setattr(instruments, "cached_rows", rows)
    store = cast(GraphStore, object())
    instruments.get_instruments_list(store, facets=facets)
    assert inline and not any(inline)
    inline.clear()
    instruments.get_instruments_list(store, q="huurwet", facets=facets)
    assert inline and all(inline)


def test_documents_partial_then_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    store = InMemoryStore()
    monkeypatch.setattr(store, "query", lambda *a, **k: iter([[]]), raising=False)
    monkeypatch.setattr(
        documents,
        "cached_rows",
        Counting([{"total": 3, "kind": [], "chamber": []}]),
    )
    first, second = _both_requests(
        monkeypatch, lambda: documents.list_documents(cast(GraphStore, store))
    )
    assert first["partial"] is True and first["total"] is None
    assert first["facets"] == {"kind": [], "chamber": []}
    assert second["total"] == 3 and "partial" not in second


def test_without_facets_nothing_is_counted_or_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(decisions, "_page", lambda *a: [])
    monkeypatch.setattr(decisions, "_add_motions", lambda *a: None)
    store = cast(GraphStore, InMemoryStore())
    page = decisions.get_decisions(store, DecisionFilters(), facets=False)
    assert page == {"total": None, "items": [], "facets": None}
