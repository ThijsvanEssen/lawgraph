"""Pieces shared by the fake stores of the tests."""

from __future__ import annotations

import math
import sys
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from typing import Any

import pytest

from lawgraph.db.queries import state as state_queries


class RawSourcesFake:
    """``insert_raw_sources`` of the store, on top of the ``insert_raw_source`` of a fake.

    The fake sees one call per record, with the fields of the record; a call that raises is
    a document the server refused. A fake keeps a record's text payload on the record, so
    ``with_payloads`` passes the records on as they are.
    """

    def with_payloads(
        self, records: Iterable[dict[str, Any]], **_: Any
    ) -> Iterator[dict[str, Any]]:
        return iter(records)

    def insert_raw_sources(
        self, docs: list[dict[str, Any]]
    ) -> list[tuple[dict[str, Any], str]]:
        failures = []
        for doc in docs:
            fields = {k: v for k, v in doc.items() if k not in ("_key", "fetched_at")}
            try:
                self.insert_raw_source(**fields)  # type: ignore[attr-defined]
            except Exception as exc:  # noqa: BLE001 — as the store: a failure per document is returned
                failures.append((doc, str(exc)))
        return failures


class ExistingKeysFake:
    """``existing_keys`` of the store, on top of the ``get_node`` of a fake."""

    def existing_keys(self, collection: str, keys: Any) -> set[str]:
        return {
            key
            for key in set(keys)
            if self.get_node(collection, key) is not None  # type: ignore[attr-defined]
        }


class FakeResponse:
    """What a client reads of a ``requests.Response``: the body as text and as bytes."""

    def __init__(self, text: str, content_type: str = "text/xml") -> None:
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"Content-Type": content_type}
        self.status_code = 200


class PipelineStateFake:
    """A store as ``pipelines/watermark`` sees it: until when each phase is covered, in
    ``state`` (phase -> moment). ``patch_pipeline_state`` points the state queries at it."""

    def __init__(self) -> None:
        self.state: dict[str, str] = {}

    def vacuum_analyze(self) -> None:
        """What the phases after retrieve ask of the database when they are done."""


def patch_pipeline_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """The queries of ``db/queries/state.py``, answered from a ``PipelineStateFake``."""

    def covered_until(store: PipelineStateFake, phase: str) -> str | None:
        return store.state.get(phase)

    def set_covered_until(store: PipelineStateFake, phase: str, began_iso: str) -> None:
        store.state[phase] = began_iso

    monkeypatch.setattr(state_queries, "covered_until", covered_until)
    monkeypatch.setattr(state_queries, "set_covered_until", set_covered_until)


# How long a test waits at most for something that happens at once in another thread: only
# reached when it never happens, so it can be ample.
PATIENCE = 10.0


def until(condition: Callable[[], bool], seconds: float = PATIENCE) -> bool:
    """Whether *condition* holds within *seconds* (another thread makes it true)."""
    end = time.monotonic() + seconds
    while not condition():
        if time.monotonic() > end:
            return False
        time.sleep(0.005)
    return True


class ManualClock:
    """A clock that stands still until the test moves it. A wait on it ends when it is
    notified or when the test moves the clock to its deadline (``move_to_wait``); the test
    learns of each wait that starts (``waits_until``), with no polling on either side."""

    def __init__(self) -> None:
        self._now = 0.0
        self.waiting_until: float | None = None
        self._condition: threading.Condition | None = None
        self._waits = threading.Condition()  # tells the test a wait started or ended

    def now(self) -> float:
        return self._now

    def wait(self, condition: threading.Condition, timeout: float) -> bool:
        """Like ``condition.wait(timeout)`` (*condition* held), in the time of this clock.
        It waits without a timeout of its own: a notify that comes as a short wait ends is
        lost (``Condition.wait`` then says it timed out)."""
        deadline = self._now + timeout
        with self._waits:
            self._condition = condition
            self.waiting_until = deadline
            self._waits.notify_all()
        try:
            condition.wait()  # notified: by another thread, or by ``move_to_wait``
            return self._now < deadline
        finally:
            with self._waits:
                self.waiting_until = None
                self._waits.notify_all()

    def waits_until(self, deadline: float) -> bool:
        """Whether a wait until *deadline* starts (another thread waits) within
        ``PATIENCE``."""
        with self._waits:
            return self._waits.wait_for(
                lambda: (
                    self.waiting_until is not None
                    and math.isclose(self.waiting_until, deadline)
                ),
                timeout=PATIENCE,
            )

    def move_to_wait(self, deadline: float) -> None:
        """Once a wait until *deadline* lasts, move the clock to its end, which ends it."""
        assert self.waits_until(deadline), (
            f"no wait until {deadline} (waiting until {self.waiting_until})"
        )
        condition = self._condition
        assert condition is not None
        with condition:
            self._now = max(self._now, self.waiting_until or deadline)
            condition.notify_all()


# What a computation that is linear in its input may take at most (seconds): one that is
# not (backtracking) takes minutes on the same input, so a busy machine never reaches it.
FAST = 5.0


def assert_fast(function: Callable[[], Any], budget: float = FAST) -> Any:
    """The result of *function*, which must return within *budget* seconds."""
    started = time.perf_counter()
    result = function()
    took = time.perf_counter() - started
    assert took < budget, f"took {took:.2f} s, more than {budget} s"
    return result


def calls_made(function: Callable[[], Any]) -> int:
    """How many functions, Python and built-in, *function* calls in this thread: a cost
    that a busy machine does not change."""
    count = 0

    def profile(frame: Any, event: str, arg: Any) -> None:
        nonlocal count
        if event in ("call", "c_call"):
            count += 1

    previous = sys.getprofile()
    sys.setprofile(profile)
    try:
        function()
    finally:
        sys.setprofile(previous)
    return count
