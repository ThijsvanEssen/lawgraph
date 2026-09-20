"""Raw records are written a buffer at a time; what a crash can lose is that buffer."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from lawgraph.db import RawSourceWriter, raw_source_doc
from lawgraph.pipelines.retrieve.base import RetrievePipelineBase, RetrieveRecord


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class _Store:
    """Counts the requests to the database and what each of them stored."""

    def __init__(self, refuse: set[str] | None = None) -> None:
        self.requests: list[list[str]] = []
        self.refuse = refuse or set()

    @property
    def stored(self) -> list[str]:
        return [external_id for request in self.requests for external_id in request]

    def insert_raw_sources(self, docs: list[dict[str, Any]]) -> list[tuple[dict, str]]:
        refused = [d for d in docs if d["external_id"] in self.refuse]
        self.requests.append(
            [d["external_id"] for d in docs if d["external_id"] not in self.refuse]
        )
        return [(d, "document too large") for d in refused]


def _doc(number: int, text: str | None = None) -> dict[str, Any]:
    return raw_source_doc(
        source="test", kind="kind", external_id=str(number), payload_text=text
    )


def test_the_key_is_that_of_source_kind_and_id_and_a_missing_id_gets_its_own() -> None:
    assert _doc(1)["_key"] == _doc(1)["_key"] != _doc(2)["_key"]
    unnamed = raw_source_doc(source="test", kind="kind", external_id=None)
    assert (
        unnamed["_key"]
        != raw_source_doc(source="test", kind="kind", external_id=None)["_key"]
    )


def test_many_small_records_are_one_request_per_five_hundred() -> None:
    store = _Store()
    with RawSourceWriter(store, clock=_Clock()) as writer:  # type: ignore[arg-type]
        for number in range(1_200):
            writer.add(_doc(number))
    assert [len(r) for r in store.requests] == [500, 500, 200]
    assert writer.written == 1_200


def test_large_records_are_written_by_size() -> None:
    store = _Store()
    with RawSourceWriter(store, max_bytes=1_000, clock=_Clock()) as writer:  # type: ignore[arg-type]
        for number in range(6):
            writer.add(_doc(number, "x" * 400))
    assert [len(r) for r in store.requests] == [3, 3]


def test_a_slow_source_is_written_every_few_seconds() -> None:
    store, clock = _Store(), _Clock()
    writer = RawSourceWriter(store, max_seconds=5, clock=clock)  # type: ignore[arg-type]
    for number in range(30):  # one record per second
        clock.now += 1
        writer.add(_doc(number))
    assert all(len(request) <= 6 for request in store.requests)
    assert (
        len(store.stored) >= 30 - 6
    )  # a crash now loses the records of 5 seconds at most


def test_a_crash_loses_at_most_the_last_buffer() -> None:
    """The process dies without any clean-up: whatever is lost sat in one buffer."""
    store = _Store()
    writer = RawSourceWriter(store, max_records=100, clock=_Clock())  # type: ignore[arg-type]
    for number in range(1_050):
        writer.add(_doc(number))
        assert len(writer) < 100
    # No flush, no ``with``: the crash.
    assert len(store.stored) == 1_000
    assert store.stored == [str(n) for n in range(1_000)]


def test_the_same_record_twice_in_a_buffer_is_stored_once_with_the_last_payload() -> (
    None
):
    store = _Store()
    with RawSourceWriter(store, clock=_Clock()) as writer:  # type: ignore[arg-type]
        writer.add(_doc(1, "old"))
        writer.add(_doc(1, "new"))
    assert store.requests == [["1"]]


# ── through a retrieve pipeline ──────────────────────────────────────────────


class _Pipeline(RetrievePipelineBase):
    def __init__(self, store: _Store, source: Iterator[RetrieveRecord]) -> None:
        super().__init__(store)  # type: ignore[arg-type]
        self.source = source

    def fetch(self, **kwargs: Any) -> Iterator[RetrieveRecord]:  # type: ignore[override]
        return self.source


def _records(count: int, then: BaseException | None = None) -> Iterator[RetrieveRecord]:
    for number in range(count):
        yield RetrieveRecord("test", "kind", str(number), payload_json={})
    if then is not None:
        raise then


def test_an_interrupt_writes_the_buffer_before_it_ends_the_run() -> None:
    store = _Store()
    with pytest.raises(KeyboardInterrupt):
        _Pipeline(store, _records(7, then=KeyboardInterrupt())).run()
    assert store.stored == [str(n) for n in range(7)]


def test_a_failing_source_writes_the_buffer_and_counts_what_was_stored() -> None:
    store = _Store()
    result = _Pipeline(store, _records(7, then=ConnectionError("dropped"))).run()
    assert store.stored == [str(n) for n in range(7)]
    assert result.created == 7
    assert result.errors == ["fetch() failed after 7 records were stored: dropped"]


def test_a_record_the_database_refuses_is_an_error_and_the_rest_is_stored() -> None:
    store = _Store(refuse={"3"})
    result = _Pipeline(store, _records(6)).run()
    assert store.stored == ["0", "1", "2", "4", "5"]
    assert (result.created, result.skipped) == (5, 1)
    assert result.errors == [
        "1 x could not be stored (first: test/kind/3: document too large)"
    ]


def test_a_failing_last_write_does_not_hide_the_interrupt() -> None:
    class Gone(_Store):
        def insert_raw_sources(
            self, docs: list[dict[str, Any]]
        ) -> list[tuple[dict, str]]:
            raise ConnectionError("database gone")

    with pytest.raises(KeyboardInterrupt):
        _Pipeline(Gone(), _records(2, then=KeyboardInterrupt())).run()


def test_ten_thousand_records_are_twenty_requests_not_ten_thousand() -> None:
    store = _Store()
    result = _Pipeline(store, _records(10_000)).run()
    assert result.created == 10_000 and len(store.requests) == 20


# ── a database that is away ──────────────────────────────────────────────────


def test_a_write_is_sent_again_while_the_database_restarts(monkeypatch) -> None:
    from lawgraph.db import store as store_module

    waits: list[float] = []
    monkeypatch.setattr(store_module, "_sleep", waits.append)
    answers: list[Any] = [
        ConnectionAbortedError("Can't connect"),
        ConnectionAbortedError("still"),
        "ok",
    ]

    def write() -> str:
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    assert store_module._retry_write("500 raw records", write) == "ok"
    assert waits == [2.0, 10.0]


def test_a_write_the_database_refuses_is_not_sent_again(monkeypatch) -> None:
    from lawgraph.db import store as store_module

    monkeypatch.setattr(
        store_module, "_sleep", lambda _s: pytest.fail("no retry expected")
    )

    def write() -> None:
        raise ValueError("document too large")

    with pytest.raises(ValueError):
        store_module._retry_write("1 raw record", write)


def test_a_database_that_stays_away_is_an_error_after_the_waits(monkeypatch) -> None:
    from lawgraph.db import store as store_module

    waits: list[float] = []
    monkeypatch.setattr(store_module, "_sleep", waits.append)

    def write() -> None:
        raise ConnectionAbortedError("Can't connect")

    with pytest.raises(ConnectionAbortedError):
        store_module._retry_write("500 raw records", write)
    assert waits == list(store_module.WRITE_RETRY_WAITS)


def test_tk_dossiers_stops_fetching_when_the_database_takes_no_writes() -> None:
    """It went on to download the next six entity types it could not store either."""
    from lawgraph.db.raw import StoreUnavailable
    from lawgraph.pipelines.retrieve.tk_dossiers import TKDossiersRetrievePipeline

    class Gone(_Store):
        def insert_raw_sources(
            self, docs: list[dict[str, Any]]
        ) -> list[tuple[dict, str]]:
            raise ConnectionAbortedError("Can't connect")

    asked: list[str] = []

    class Client:
        def fetch_dossiers(self, since=None):
            asked.append("dossiers")
            return iter([{"Id": "d1"}])

        def __getattr__(self, name: str):
            def fetch(**_kw: Any):
                asked.append(name)
                return iter([])

            return fetch

    with pytest.raises(StoreUnavailable):
        TKDossiersRetrievePipeline(store=Gone(), client=Client()).run()  # type: ignore[arg-type]
    assert asked == ["dossiers"]
