"""Tests against the PostgreSQL of ``docker-compose.test.yml``, like ``tests/integration``::

    docker compose -f docker-compose.test.yml up -d postgres-test
    ALLOW_DB_TESTS=1 pytest tests/pg

They talk to ``LAWGRAPH_TEST_DB_URL`` (default the server on port 5433) and create and drop
databases named ``lawgraph_it_...`` there; never the database of ``.env``.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from lawgraph.db import GraphStore
from lawgraph.db import store as store_module
from lawgraph.db.schema import ensure_schema
from tests.databases import fresh_database

TEST_URL = os.environ.get(
    "LAWGRAPH_TEST_DB_URL",
    "postgresql://lawgraph:lawgraph-test@localhost:5433/lawgraph",
)


def _reachable() -> bool:
    try:
        psycopg.connect(TEST_URL, connect_timeout=3).close()
    except psycopg.OperationalError:
        return False
    return True


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if os.environ.get("ALLOW_DB_TESTS") != "1":
        reason = "Database tests disabled (set ALLOW_DB_TESTS=1 to enable)."
    elif not _reachable():
        reason = (
            f"No PostgreSQL at {TEST_URL} "
            "(docker compose -f docker-compose.test.yml up -d postgres-test)."
        )
    else:
        return
    for item in items:
        if "tests/pg" in str(item.fspath):
            item.add_marker(pytest.mark.skip(reason=reason))


@pytest.fixture()
def database_url() -> Iterator[str]:
    """The URL of a fresh, empty database on the test server, dropped afterwards."""
    with fresh_database(TEST_URL) as name:
        yield f"{TEST_URL.rsplit('/', 1)[0]}/{name}"


@pytest.fixture()
def conn(database_url: str) -> Iterator[psycopg.Connection]:
    """A connection to a fresh database with the schema."""
    with psycopg.connect(database_url, autocommit=True) as connection:
        ensure_schema(connection)
        yield connection


@pytest.fixture()
def store(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[GraphStore]:
    """The store on a fresh database, with a payload store of its own."""
    server, name = database_url.rsplit("/", 1)
    monkeypatch.setattr(store_module, "DB_URL", server)
    monkeypatch.setattr(store_module, "DB_NAME", name)
    monkeypatch.setattr(
        store_module, "PAYLOAD_STORE", f"file://{tmp_path / 'payloads'}"
    )
    opened = GraphStore()
    try:
        yield opened
    finally:
        opened.close()
