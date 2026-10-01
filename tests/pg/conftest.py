"""Tests against the PostgreSQL of ``docker-compose.test.yml``, like ``tests/integration``::

    docker compose -f docker-compose.test.yml up -d postgres-test
    ALLOW_DB_TESTS=1 pytest tests/pg

They talk to ``LAWGRAPH_TEST_DB_URL`` (default the server on port 5433) and create and drop
databases named ``lawgraph_it_...`` there; never the database of ``.env``.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import psycopg
import pytest

from lawgraph.db.schema import create_database_sql, ensure_schema

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
    name = f"lawgraph_it_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(TEST_URL, autocommit=True) as admin:
        admin.execute(create_database_sql(name).encode())
        try:
            yield f"{TEST_URL.rsplit('/', 1)[0]}/{name}"
        finally:
            admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)'.encode())


@pytest.fixture()
def conn(database_url: str) -> Iterator[psycopg.Connection]:
    """A connection to a fresh database with the schema."""
    with psycopg.connect(database_url, autocommit=True) as connection:
        ensure_schema(connection)
        yield connection
