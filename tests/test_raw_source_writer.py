"""Raw records are written a buffer at a time; what a crash can lose is that buffer."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from lawgraph.db import RawSourceWriter, raw_source_doc
from lawgraph.pipelines.retrieve.base import RetrievePipelineBase, RetrieveRecord
from tests.fakes import InMemoryStore, external_ids


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _store() -> tuple[InMemoryStore, list[list[str]]]:
    """A store, and the requests to it with what each of them stored."""
    store = InMemoryStore()
    requests: list[list[str]] = []
    write = store.insert_raw_sources

    def counted(docs: list[dict[str, Any]]) -> None:
        write(docs)
        requests.append([d["external_id"] for d in docs])

    store.insert_raw_sources = counted  # type: ignore[method-assign]
    return store, requests


def _gone(error: Exception) -> InMemoryStore:
    """A store whose database cannot be reached."""
    store = InMemoryStore()

    def insert_raw_sources(docs: list[dict[str, Any]]) -> None:
        raise error

    store.insert_raw_sources = insert_raw_sources  # type: ignore[method-assign]
    return store


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
    store, requests = _store()
    with RawSourceWriter(store, clock=_Clock()) as writer:  # type: ignore[arg-type]
        for number in range(1_200):
            writer.add(_doc(number))
    assert [len(r) for r in requests] == [500, 500, 200]
    assert writer.written == 1_200


def test_large_records_are_written_by_size() -> None:
    store, requests = _store()
    with RawSourceWriter(store, max_bytes=1_000, clock=_Clock()) as writer:  # type: ignore[arg-type]
        for number in range(6):
            writer.add(_doc(number, "x" * 400))
    assert [len(r) for r in requests] == [3, 3]


def test_a_slow_source_is_written_every_few_seconds() -> None:
    (store, requests), clock = _store(), _Clock()
    writer = RawSourceWriter(store, max_seconds=5, clock=clock)  # type: ignore[arg-type]
    for number in range(30):  # one record per second
        clock.now += 1
        writer.add(_doc(number))
    assert all(len(request) <= 6 for request in requests)
    assert (
        len(external_ids(store)) >= 30 - 6
    )  # a crash now loses the records of 5 seconds at most


def test_a_crash_loses_at_most_the_last_buffer() -> None:
    """The process dies without any clean-up: whatever is lost sat in one buffer."""
    store, _ = _store()
    writer = RawSourceWriter(store, max_records=100, clock=_Clock())  # type: ignore[arg-type]
    for number in range(1_050):
        writer.add(_doc(number))
        assert len(writer) < 100
    # No flush, no ``with``: the crash.
    assert len(external_ids(store)) == 1_000
    assert external_ids(store) == [str(n) for n in range(1_000)]


def test_the_same_record_twice_in_a_buffer_is_stored_once_with_the_last_payload() -> (
    None
):
    store, requests = _store()
    with RawSourceWriter(store, clock=_Clock()) as writer:  # type: ignore[arg-type]
        writer.add(_doc(1, "old"))
        writer.add(_doc(1, "new"))
    assert requests == [["1"]]


# ── through a retrieve pipeline ──────────────────────────────────────────────


class _Pipeline(RetrievePipelineBase):
    def __init__(self, store: InMemoryStore, source: Iterator[RetrieveRecord]) -> None:
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
    store, _ = _store()
    with pytest.raises(KeyboardInterrupt):
        _Pipeline(store, _records(7, then=KeyboardInterrupt())).run()
    assert external_ids(store) == [str(n) for n in range(7)]


def test_a_failing_source_writes_the_buffer_and_counts_what_was_stored() -> None:
    store, _ = _store()
    result = _Pipeline(store, _records(7, then=ConnectionError("dropped"))).run()
    assert external_ids(store) == [str(n) for n in range(7)]
    assert result.created == 7
    assert result.errors == [
        "fetch() failed after 7 records were stored: ConnectionError: dropped"
    ]


def test_a_failing_last_write_does_not_hide_the_interrupt() -> None:
    with pytest.raises(KeyboardInterrupt):
        _Pipeline(
            _gone(ConnectionError("database gone")),
            _records(2, then=KeyboardInterrupt()),
        ).run()


def test_ten_thousand_records_are_twenty_requests_not_ten_thousand() -> None:
    store, requests = _store()
    result = _Pipeline(store, _records(10_000)).run()
    assert result.created == 10_000 and len(requests) == 20


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


def test_a_write_that_ran_past_its_time_is_not_sent_again(monkeypatch) -> None:
    """A statement cancelled by ``statement_timeout`` would run as long a second time."""
    import psycopg

    from lawgraph.db import store as store_module

    monkeypatch.setattr(
        store_module, "_sleep", lambda _s: pytest.fail("no retry expected")
    )
    calls: list[int] = []

    def write() -> None:
        calls.append(1)
        raise psycopg.errors.QueryCanceled(
            "canceling statement due to statement timeout"
        )

    with pytest.raises(psycopg.errors.QueryCanceled):
        store_module._retry_write("a statement", write)
    assert calls == [1]


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
        TKDossiersRetrievePipeline(
            store=_gone(ConnectionAbortedError("Can't connect")), client=Client()
        ).run()  # type: ignore[arg-type]
    assert asked == ["dossiers"]


def test_a_stop_request_ends_the_step_after_storing_what_it_has() -> None:
    from lawgraph.pipelines.base import STOP

    store, _ = _store()

    def records() -> Iterator[RetrieveRecord]:
        for number in range(100):
            if number == 7:
                STOP.set()  # the main thread was interrupted
            yield RetrieveRecord("test", "kind", str(number), payload_json={})

    try:
        with pytest.raises(KeyboardInterrupt):
            _Pipeline(store, records()).run()
    finally:
        STOP.clear()
    assert external_ids(store) == [str(n) for n in range(7)]
