"""``cached_data_as_of`` (carried by ``/api/stats``, the coverage and the feed) is read again
in the background before it expires: a request never reads the newest fetch of every source
itself while it still has the kept answer, and the warm-up has it ready."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterable, Iterator

import pytest

from lawgraph.api import warm
from lawgraph.db import request_context, version_cache
from lawgraph.db.queries import stats


class _Store:
    name = "data-as-of"

    def data_version(self, tables: Iterable[str] | None = None) -> str:
        return "1"


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    version_cache.clear()
    yield
    version_cache.clear()


def test_a_request_takes_the_kept_answer_while_the_new_one_is_read_ahead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    reads = 0
    read = threading.Event()

    def get(_store: object) -> dict[str, int]:
        nonlocal reads
        reads += 1
        read.set()
        return {"read": reads}

    monkeypatch.setattr(stats, "get_data_as_of", get)
    store = _Store()
    token = request_context.set_read_deadline(10.0)
    try:
        assert stats.cached_data_as_of(store) == {"read": 1}  # type: ignore[arg-type]
        now[0] += 50  # past three quarters of the minute, not yet expired
        read.clear()
        assert stats.cached_data_as_of(store) == {"read": 1}  # type: ignore[arg-type]
        assert read.wait(5)
    finally:
        request_context.reset_read_deadline(token)
    assert reads == 2


def test_the_warm_up_reads_it_once_after_the_stats() -> None:
    names = [part.name for part in warm.PARTS]
    assert names.index("data as of") == names.index("stats") + 1
    part = next(p for p in warm.PARTS if p.name == "data as of")
    assert part.tables is None
