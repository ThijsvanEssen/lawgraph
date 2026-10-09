"""A test database dropped takes the stores a test left open on it along."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from lawgraph.db import GraphStore
from lawgraph.db import store as store_module
from tests.databases import fresh_database
from tests.pg.conftest import TEST_URL


def test_no_pool_of_a_dropped_test_database_goes_on_reconnecting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with fresh_database(TEST_URL) as name:
        monkeypatch.setattr(store_module, "DB_URL", TEST_URL.rsplit("/", 1)[0])
        monkeypatch.setattr(store_module, "DB_NAME", name)
        monkeypatch.setattr(
            store_module, "PAYLOAD_STORE", f"file://{tmp_path / 'payloads'}"
        )
        left_open = GraphStore()
        with store_module.in_background():
            assert list(left_open.query("SELECT 1")) == [1]
        assert left_open._background_pool is not None
    assert left_open.pool.closed
    assert left_open._background_pool.closed
    assert not [
        thread.name
        for thread in threading.enumerate()
        if thread.name.startswith("lawgraph-background")
    ]
