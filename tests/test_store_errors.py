"""``GraphStore`` names what went wrong: a database it cannot reach is
``DatabaseUnavailable``, an outdated schema stays ``SchemaOutdated``; a pool it opened is
closed either way."""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest

from lawgraph.db import store
from lawgraph.db.schema import SchemaOutdated
from lawgraph.db.store import DatabaseUnavailable, GraphStore


class _Pool:
    opened: list[_Pool] = []

    def __init__(self, *_args: Any, fail: Exception | None = None, **_kw: Any) -> None:
        self.closed = False
        self.fail = fail
        _Pool.opened.append(self)

    @contextlib.contextmanager
    def connection(self, timeout: float | None = None) -> Iterator[object]:
        if self.fail is not None:
            raise self.fail
        yield object()

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def pools(monkeypatch: pytest.MonkeyPatch) -> list[_Pool]:
    _Pool.opened = []
    monkeypatch.setattr(store, "_create_database_if_missing", lambda: None)
    monkeypatch.setattr(store, "ConnectionPool", _Pool)
    return _Pool.opened


def test_an_outdated_schema_stays_schema_outdated_and_closes_the_pool(
    pools: list[_Pool], monkeypatch: pytest.MonkeyPatch
) -> None:
    def outdated(conn: object, **_kw: object) -> None:
        raise SchemaOutdated("schema outdated")

    monkeypatch.setattr(store, "ensure_schema", outdated)
    with pytest.raises(SchemaOutdated):
        GraphStore()
    assert [pool.closed for pool in pools] == [True]


def test_a_server_that_cannot_be_reached_is_database_unavailable(
    pools: list[_Pool], monkeypatch: pytest.MonkeyPatch
) -> None:
    def refused(conn: object, **_kw: object) -> None:
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(store, "ensure_schema", refused)
    with pytest.raises(DatabaseUnavailable, match="connection refused"):
        GraphStore()
    assert [pool.closed for pool in pools] == [True]


def _store_on(pool: _Pool) -> GraphStore:
    graph = GraphStore.__new__(GraphStore)
    graph.pool = pool  # type: ignore[assignment]
    return graph


def test_a_read_that_loses_the_server_is_database_unavailable() -> None:
    gone = psycopg.OperationalError("server closed the connection unexpectedly")
    graph = _store_on(_Pool(fail=gone))
    with pytest.raises(DatabaseUnavailable):
        list(graph.query("SELECT 1"))
    with pytest.raises(DatabaseUnavailable):
        graph.ping()


def test_a_read_the_server_refuses_keeps_its_own_error() -> None:
    refused = psycopg.errors.LockNotAvailable("could not obtain lock")
    graph = _store_on(_Pool(fail=refused))
    with pytest.raises(psycopg.errors.LockNotAvailable):
        list(graph.query("SELECT 1"))
