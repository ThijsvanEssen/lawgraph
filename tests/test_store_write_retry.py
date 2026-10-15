"""A bulk upsert is sent again while the database is unreachable: each statement at most
``1 + len(WRITE_RETRY_WAITS)`` times, with those waits in between."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

import psycopg
import pytest
from psycopg_pool import ConnectionPool

from lawgraph.db import GraphStore
from lawgraph.db import store as store_module


class _UnreachablePool:
    """A pool whose every connection is refused, counting the attempts."""

    def __init__(self) -> None:
        self.attempts = 0

    def connection(self) -> Any:
        self.attempts += 1
        raise psycopg.OperationalError("server closed the connection unexpectedly")


def _store(pool: _UnreachablePool) -> GraphStore:
    store = GraphStore.__new__(GraphStore)
    store.pool = cast(ConnectionPool, pool)
    return store


def _upsert_nodes(store: GraphStore) -> Any:
    return store.bulk_insert_or_update_nodes(
        "dossiers", [{"key": "1", "type": "dossier", "labels": [], "props": {}}]
    )


def _upsert_edges(store: GraphStore) -> Any:
    return store.bulk_insert_or_update_edges(
        [{"key": "e1", "from_id": "dossiers/1", "to_id": "dossiers/2", "relation": "X"}]
    )


@pytest.mark.parametrize("upsert", [_upsert_nodes, _upsert_edges])
def test_an_upsert_is_sent_once_per_wait_and_then_fails(
    upsert: Callable[[GraphStore], Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    waits: list[float] = []
    monkeypatch.setattr(store_module, "_sleep", waits.append)
    pool = _UnreachablePool()

    with pytest.raises(psycopg.OperationalError):
        upsert(_store(pool))

    assert pool.attempts == 1 + len(store_module.WRITE_RETRY_WAITS)
    assert waits == list(store_module.WRITE_RETRY_WAITS)
