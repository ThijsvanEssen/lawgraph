"""A read under a budget of its own: capped at what the request has left, cut off as
``ReadTimedOut`` into the answer without it, a client that went away (``RequestCancelled``)
up to the request."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest

from lawgraph.api.routes import feed as feed_routes
from lawgraph.api.routes import render
from lawgraph.db import store as store_module
from lawgraph.db.queries import _bm25, decisions, nodes, paths, search, seo
from lawgraph.db.queries import feed as feed_queries
from lawgraph.db.queries.feed import FeedFilters
from lawgraph.db.store import ReadTimedOut, RequestCancelled
from tests.fakes import InMemoryStore


@pytest.fixture(autouse=True)
def _a_request(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A request with 30 s left; no read reaches a database."""
    monkeypatch.setattr(store_module, "READ_TIMEOUT_MS", 600_000)
    token = store_module.set_read_deadline(30.0)
    try:
        yield
    finally:
        store_module.reset_read_deadline(token)


def test_a_budget_is_capped_at_what_the_request_has_left() -> None:
    token = store_module.set_read_deadline(1.0)
    try:
        with store_module.read_budget(3.0, "a count"):
            assert store_module._read_budget_ms() <= 1000
        assert store_module._read_budget_ms() <= 1000
    finally:
        store_module.reset_read_deadline(token)
    with store_module.read_budget(3.0, "a count"):
        assert 2000 < store_module._read_budget_ms() <= 3000
    assert store_module._read_budget_ms() > 3000


def test_a_reserve_is_kept_from_what_the_request_has_left() -> None:
    token = store_module.set_read_deadline(1.0)
    try:
        with store_module.read_budget(3.0, "paths", reserve=0.4):
            assert store_module._read_budget_ms() <= 600
    finally:
        store_module.reset_read_deadline(token)


def test_a_read_past_its_budget_is_cut_off_and_logged_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("INFO"), store_module.read_budget(0.5, "the counts") as budget:
        raise ReadTimedOut("past")
    assert budget.ran_out
    assert [m for m in caplog.messages if "the counts" in m] == [
        "the counts took over 0.5 s: answered without it."
    ]
    with store_module.read_budget(0.5, "the counts") as budget:
        pass
    assert not budget.ran_out


def test_a_cancelled_read_goes_up_through_a_budget() -> None:
    with (
        pytest.raises(RequestCancelled),
        store_module.read_budget(0.5, "the counts"),
    ):
        raise RequestCancelled("gone")
    assert store_module.read_time_left() is not None


def _cancelled(*args: Any, **kwargs: Any) -> Any:
    raise RequestCancelled("The client went away.")


def _get_feed(monkeypatch: pytest.MonkeyPatch) -> Callable[[], Any]:
    monkeypatch.setattr(feed_queries, "_page_items", lambda *a: ([], None))
    monkeypatch.setattr(feed_queries, "_counts_of_events", _cancelled)
    return lambda: feed_queries.get_feed(object(), FeedFilters())  # type: ignore[arg-type]


def _feed_words(monkeypatch: pytest.MonkeyPatch) -> Callable[[], Any]:
    monkeypatch.setattr(feed_queries, "_bounded_page", lambda *a: None)
    monkeypatch.setattr(feed_queries, "_rows", _cancelled)
    return lambda: feed_queries._page_items(
        object(),  # type: ignore[arg-type]
        FeedFilters(q="woord"),
        None,
        10,
    )


def _paths(monkeypatch: pytest.MonkeyPatch) -> Callable[[], Any]:
    monkeypatch.setattr(paths, "_shortest", _cancelled)
    return lambda: paths._search(None, ["a", "b"], 3, {})  # type: ignore[arg-type]


def _search_live(monkeypatch: pytest.MonkeyPatch) -> Callable[[], Any]:
    return lambda: search._within_budget(_cancelled)


def _search_parser(monkeypatch: pytest.MonkeyPatch) -> Callable[[], Any]:
    monkeypatch.setattr(search, "load_notation_parser", _cancelled)
    return lambda: search.kept_notation_parser(object(), 1.0)  # type: ignore[arg-type]


def _nodes(monkeypatch: pytest.MonkeyPatch) -> Callable[[], Any]:
    monkeypatch.setattr(nodes, "lasting", _cancelled)
    return lambda: nodes._kept_lids(
        object(),  # type: ignore[arg-type]
        "articles/x",
        None,  # type: ignore[arg-type]
        None,
        wait=False,
    )


def _decision_total(monkeypatch: pytest.MonkeyPatch) -> Callable[[], Any]:
    store = InMemoryStore()
    monkeypatch.setattr(store, "data_version", lambda *a: "v", raising=False)
    monkeypatch.setattr(decisions, "_kept_counts", _cancelled)
    return lambda: decisions.counted_total(store, decisions.DecisionFilters())  # type: ignore[arg-type]


def _seo(monkeypatch: pytest.MonkeyPatch) -> Callable[[], Any]:
    return lambda: seo._within_budget(_cancelled, [])


def _bm25_stats(monkeypatch: pytest.MonkeyPatch) -> Callable[[], Any]:
    monkeypatch.setattr(_bm25, "_stats", _cancelled)
    return lambda: _bm25._stats_now(object(), "judgments")


def _feed_periods(monkeypatch: pytest.MonkeyPatch) -> Callable[[], Any]:
    monkeypatch.setattr(feed_routes.feed_events, "get_periods", _cancelled)
    return lambda: feed_routes.get_feed_periods_route(
        object(),  # type: ignore[arg-type]
        FeedFilters(),
    )


def _render_title(monkeypatch: pytest.MonkeyPatch) -> Callable[[], Any]:
    store = InMemoryStore()
    monkeypatch.setattr(store, "get_document", _cancelled)
    return lambda: render._title_page(store, "articles/x", "/x")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "call",
    [
        _get_feed,
        _feed_words,
        _paths,
        _search_live,
        _search_parser,
        _nodes,
        _decision_total,
        _seo,
        _bm25_stats,
        _feed_periods,
        _render_title,
    ],
)
def test_a_client_that_went_away_is_not_answered_without_the_read(
    monkeypatch: pytest.MonkeyPatch,
    call: Callable[[pytest.MonkeyPatch], Callable[[], Any]],
) -> None:
    with pytest.raises(RequestCancelled):
        call(monkeypatch)()


def test_the_title_of_a_page_reads_within_what_the_request_has_left(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[int] = []
    store = InMemoryStore()
    monkeypatch.setattr(
        store, "get_document", lambda *a: seen.append(store_module._read_budget_ms())
    )
    token = store_module.set_read_deadline(0.1)
    try:
        render._title_page(store, "articles/x", "/x")  # type: ignore[arg-type]
    finally:
        store_module.reset_read_deadline(token)
    assert seen and seen[0] <= 100
