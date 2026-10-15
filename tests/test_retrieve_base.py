"""The base of the retrieve pipelines: a source that fails, a crash or an interrupt halfway, and
what a re-run after a crash leaves alone."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Iterator
from typing import Any

import pytest
import requests

from lawgraph.db.queries import raw as raw_queries
from lawgraph.pipelines.retrieve.base import (
    FailureStreak,
    RetrievePipelineBase,
    RetrieveRecord,
    SourceDown,
)
from tests.fakes import (
    InMemoryStore,
    external_ids,
    raw_record,
)

pytestmark = pytest.mark.usefixtures("raw_reads")


def test_a_streak_of_failures_means_the_source_is_down() -> None:
    streak = FailureStreak("Source", limit=3)
    streak.failed("a", RuntimeError("x"))
    streak.failed("b", RuntimeError("x"))
    with pytest.raises(
        SourceDown, match="3 requests in a row failed.*seems to be down"
    ):
        streak.failed("c", RuntimeError("boom"))


def test_a_success_ends_the_streak() -> None:
    streak = FailureStreak("Source", limit=3)
    for _ in range(10):
        streak.failed("a", RuntimeError("x"))
        streak.failed("b", RuntimeError("x"))
        streak.ok()  # never three in a row


def _record(external_id: str) -> RetrieveRecord:
    return RetrieveRecord(
        source="test", kind="test-kind", external_id=external_id, payload_json={}
    )


class _Pipeline(RetrievePipelineBase):
    def __init__(self, store: InMemoryStore, source: Iterable[RetrieveRecord]) -> None:
        super().__init__(store)
        self.source = source

    def fetch(self, **kwargs: Any) -> Iterable[RetrieveRecord]:
        return self.source


def test_a_failure_halfway_keeps_what_was_stored_and_is_an_error() -> None:
    def source() -> Iterator[RetrieveRecord]:
        yield _record("a")
        yield _record("b")
        raise requests.ConnectionError("connection dropped")

    store = InMemoryStore()
    result = _Pipeline(store, source()).run()

    assert external_ids(store) == ["a", "b"]
    assert result.created == 2
    assert len(result.errors) == 1
    assert "after 2 records were stored" in result.errors[0]
    assert "connection dropped" in result.errors[0]


def test_an_interrupt_keeps_what_was_stored() -> None:
    def source() -> Iterator[RetrieveRecord]:
        yield _record("a")
        raise KeyboardInterrupt

    store = InMemoryStore()
    with pytest.raises(KeyboardInterrupt):
        _Pipeline(store, source()).run()
    assert external_ids(store) == ["a"]


def test_a_list_from_fetch_still_works() -> None:
    store = InMemoryStore()
    result = _Pipeline(store, [_record("a"), _record("b")]).run()
    assert (external_ids(store), result.created) == (["a", "b"], 2)


def test_recently_stored_asks_for_the_last_24_hours(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: dict[str, Any] = {}

    def ids_stored_since(store: InMemoryStore, **kwargs: Any) -> list[str]:
        asked.update(kwargs)
        return ["x"]

    monkeypatch.setattr(raw_queries, "ids_stored_since", ids_stored_since)
    done = _Pipeline(InMemoryStore(), iter([]))._recently_stored("src", "kind")
    assert done == {"x"}
    assert asked["source"] == "src" and asked["kind"] == "kind"
    cutoff = dt.datetime.fromisoformat(asked["cutoff_iso"].replace("Z", "+00:00"))
    age = dt.datetime.now(dt.UTC) - cutoff
    assert dt.timedelta(hours=23, minutes=59) < age < dt.timedelta(hours=24, minutes=1)


def test_stored_at_reads_fetched_at_as_utc() -> None:
    store = InMemoryStore(
        raw=[
            raw_record("src", "kind", "a", fetched_at="2026-10-14T08:00:00Z"),
            raw_record("src", "kind", "b", fetched_at="2026-10-14T09:00:00+00:00"),
        ]
    )

    stored = _Pipeline(store, iter([]))._stored_at("src", "kind")

    utc = dt.UTC
    assert stored == {
        "a": dt.datetime(2026, 10, 14, 8, tzinfo=utc),
        "b": dt.datetime(2026, 10, 14, 9, tzinfo=utc),
    }


def test_stored_at_fails_on_a_fetched_at_that_is_no_moment() -> None:
    """``fetched_at`` is always written by ``iso_timestamp``: another value is a bug, not
    a record to fetch again."""
    store = InMemoryStore(
        raw=[
            raw_record("src", "kind", "a", fetched_at="2026-10-14T08:00:00Z"),
            raw_record("src", "kind", "b", fetched_at="yesterday"),
        ]
    )

    with pytest.raises(ValueError) as raised:
        _Pipeline(store, iter([]))._stored_at("src", "kind")

    assert "src kind b" in "\n".join(raised.value.__notes__)
