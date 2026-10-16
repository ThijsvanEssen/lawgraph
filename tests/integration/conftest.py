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

import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from tests.databases import require_test_server, skip_unless_asked_for

TEST_URL = os.environ.get(
    "LAWGRAPH_TEST_DB_URL",
    "postgresql://lawgraph:lawgraph-test@localhost:5433/lawgraph",
)
# The server, without a database: the store adds the name.
TEST_SERVER = TEST_URL.rsplit("/", 1)[0]
ROOT = Path(__file__).resolve().parents[2]


def pytest_sessionstart(session: pytest.Session) -> None:
    require_test_server(TEST_URL, "docker compose -f docker-compose.test.yml up -d")


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    skip_unless_asked_for(items, "tests/integration")


@pytest.fixture()
def payload_store(tmp_path: Path) -> str:
    """The payload store of the test: a directory of its own."""
    return f"file://{tmp_path / 'payloads'}"


@pytest.fixture()
def database(monkeypatch: pytest.MonkeyPatch, payload_store: str) -> Iterator[str]:
    """A fresh database on the test server, and a payload store of its own; ``GraphStore()``
    in this process uses both."""
    from lawgraph.db import store as store_module
    from tests.databases import fresh_database

    with fresh_database(TEST_URL) as name:
        monkeypatch.setattr(store_module, "DB_URL", TEST_SERVER)
        monkeypatch.setattr(store_module, "DB_NAME", name)
        monkeypatch.setattr(store_module, "PAYLOAD_STORE", payload_store)
        yield name


@pytest.fixture()
def cli(
    database: str, payload_store: str
) -> Callable[..., subprocess.CompletedProcess[str]]:
    """Run ``lawgraph <args>`` as a process of its own against the test database."""
    return lawgraph_runner(database, payload_store)


def lawgraph_runner(
    database: str, payload_store: str
) -> Callable[..., subprocess.CompletedProcess[str]]:
    """``lawgraph <args>`` as a process of its own against *database* on the test server,
    with *payload_store*: what ``cli`` gives a test, for a fixture of a wider scope too."""

    def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        env = {
            **os.environ,
            "LAWGRAPH_DB_URL": TEST_SERVER,
            "LAWGRAPH_DB_NAME": database,
            "LAWGRAPH_PAYLOAD_STORE": payload_store,
            "LAWGRAPH_LOG_LEVEL": "INFO",
            # The code of this checkout, also when the installed package is another one.
            "PYTHONPATH": str(ROOT / "src"),
            "NO_COLOR": "1",
        }
        done = subprocess.run(
            [sys.executable, "-m", "lawgraph", *args],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=1800,
        )
        if check and done.returncode != 0:
            raise AssertionError(
                f"lawgraph {' '.join(args)} exited {done.returncode}:\n{done.stderr[-3000:]}"
            )
        return done

    return run
