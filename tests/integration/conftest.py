"""Integration tests: the real CLI and pipelines against a real, deliberately small
PostgreSQL. A test that writes the graph itself and reads a query or a route is in
``tests/pg``.

The unit suite runs on fake stores and never executes a query, so what only a server shows
(a result built in its memory, a cursor that is killed, a restart in the middle of a run)
stays invisible there. These tests need the test database of ``docker-compose.test.yml``::

    docker compose -f docker-compose.test.yml up -d
    ALLOW_DB_TESTS=1 pytest tests/integration

They never touch the database of ``.env``: they talk to ``LAWGRAPH_TEST_DB_URL`` (default the
server on port 5433, as ``tests/pg``) and create and drop databases named ``lawgraph_it_...``
there.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.databases import api as api
from tests.databases import database as database
from tests.databases import lawgraph_runner, require_test_server, skip_unless_asked_for
from tests.databases import payloads as payloads
from tests.databases import store as store


def pytest_sessionstart(session: pytest.Session) -> None:
    require_test_server("docker compose -f docker-compose.test.yml up -d")


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    skip_unless_asked_for(items, "tests/integration")


@pytest.fixture()
def cli(
    database: str, payloads: Path
) -> Callable[..., subprocess.CompletedProcess[str]]:
    """Run ``lawgraph <args>`` as a process of its own against the test database."""
    return lawgraph_runner(database, payloads)
