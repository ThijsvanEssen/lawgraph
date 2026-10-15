"""A data version that cannot be read: nothing is kept, every request computes its answer,
and the log says so once, not on every request."""

from __future__ import annotations

import pytest

from lawgraph.db import version_cache


class _Broken:
    """A database whose versions cannot be read (``lg_data_version`` gone)."""

    name = "unread"

    def __init__(self) -> None:
        self.failure: Exception | None = RuntimeError(
            "relation lg_data_version is gone"
        )

    def data_version(self) -> str:
        return "1"

    def table_versions(self) -> dict[str, int]:
        if self.failure is not None:
            raise self.failure
        return {"judgments": 1}


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]


def test_a_version_that_cannot_be_read_is_computed_and_logged_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = _Broken()
    computed: list[int] = []

    def compute() -> int:
        computed.append(1)
        return len(computed)

    with caplog.at_level("WARNING"):
        answers = [version_cache.cached(store, "count", compute) for _ in range(3)]
    assert answers == [1, 2, 3]  # nothing kept
    assert _warnings(caplog) == [
        "The data version cannot be read; every answer is computed anew:"
        " RuntimeError: relation lg_data_version is gone"
    ]


def test_another_failure_and_one_after_a_read_are_logged_again(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = _Broken()
    with caplog.at_level("WARNING"):
        version_cache.cached(store, "count", lambda: 0)
        store.failure = OSError("connection refused")
        version_cache.cached(store, "count", lambda: 0)
        store.failure = None
        version_cache.cached(store, "count", lambda: 0)  # read: kept from now on
        store.failure = OSError("connection refused")
        version_cache.cached(store, "count", lambda: 0)
    assert [w.rsplit(": ", 1)[1] for w in _warnings(caplog)] == [
        "relation lg_data_version is gone",
        "connection refused",
        "connection refused",
    ]


def test_a_store_without_a_version_keeps_nothing_and_logs_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = object()
    with caplog.at_level("WARNING"):
        assert version_cache.cached(store, "count", lambda: 1) == 1
    assert not isinstance(store, version_cache.VersionedStore)
    assert _warnings(caplog) == []
