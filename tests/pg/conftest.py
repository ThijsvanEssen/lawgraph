"""Tests against the PostgreSQL of ``docker-compose.test.yml``, like ``tests/integration``:
a test here writes the graph directly and reads a query or a route; one that runs the CLI or a
pipeline is in ``tests/integration``::

    docker compose -f docker-compose.test.yml up -d postgres-test
    ALLOW_DB_TESTS=1 pytest tests/pg

They talk to ``LAWGRAPH_TEST_DB_URL`` (default the server on port 5433) and create and drop
databases named ``lawgraph_it_...`` there; never the database of ``.env``.
"""

from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest

from lawgraph.db.schema import ensure_schema
from tests.databases import (
    TEST_URL,
    fresh_database,
    require_test_server,
    skip_unless_asked_for,
    url_of,
)
from tests.databases import api as api
from tests.databases import database as database
from tests.databases import payloads as payloads
from tests.databases import store as store


def pytest_sessionstart(session: pytest.Session) -> None:
    require_test_server("docker compose -f docker-compose.test.yml up -d postgres-test")


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    skip_unless_asked_for(items, "tests/pg")


@pytest.fixture()
def database_url(database: str) -> str:
    """The URL of ``database``."""
    return url_of(database)


@pytest.fixture()
def conn(database_url: str) -> Iterator[psycopg.Connection]:
    """A connection to a fresh database with the schema."""
    with psycopg.connect(database_url, autocommit=True) as connection:
        ensure_schema(connection)
        yield connection


@pytest.fixture(scope="module")
def shared_conn() -> Iterator[psycopg.Connection]:
    """One connection, for the whole module, to a fresh database with the schema: for tests
    that only read (plan a statement, evaluate an expression) and so cannot meet."""
    with fresh_database(TEST_URL) as name:
        with psycopg.connect(url_of(name), autocommit=True) as connection:
            ensure_schema(connection)
            yield connection
