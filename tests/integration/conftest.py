"""Integration tests: the real code against a real, deliberately small PostgreSQL.

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
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import psycopg
import pytest

TEST_URL = os.environ.get(
    "LAWGRAPH_TEST_DB_URL",
    "postgresql://lawgraph:lawgraph-test@localhost:5433/lawgraph",
)
# The server, without a database: the store adds the name.
TEST_SERVER = TEST_URL.rsplit("/", 1)[0]
ROOT = Path(__file__).resolve().parents[2]


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
        reason = "Integration tests disabled (set ALLOW_DB_TESTS=1 to enable)."
    elif not _reachable():
        reason = (
            f"No test database at {TEST_URL} "
            "(docker compose -f docker-compose.test.yml up -d)."
        )
    else:
        return
    for item in items:
        if "tests/integration" in str(item.fspath):
            item.add_marker(pytest.mark.skip(reason=reason))


@pytest.fixture()
def payload_store(tmp_path: Path) -> str:
    """The payload store of the test: a directory of its own."""
    return f"file://{tmp_path / 'payloads'}"


@pytest.fixture()
def database(monkeypatch: pytest.MonkeyPatch, payload_store: str) -> Iterator[str]:
    """A fresh database on the test server, and a payload store of its own; ``ArangoStore()``
    in this process uses both."""
    from lawgraph.core.cache import TTLCache
    from lawgraph.db import store as store_module
    from lawgraph.db.schema import create_database_sql

    name = f"lawgraph_it_{uuid.uuid4().hex[:10]}"
    monkeypatch.setattr(store_module, "DB_URL", TEST_SERVER)
    monkeypatch.setattr(store_module, "DB_NAME", name)
    monkeypatch.setattr(store_module, "PAYLOAD_STORE", payload_store)
    # What the caches of the API and the search hold was read from another test's database.
    TTLCache.clear_all()
    with psycopg.connect(TEST_URL, autocommit=True) as admin:
        admin.execute(create_database_sql(name).encode())
        try:
            yield name
        finally:
            admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)'.encode())


@pytest.fixture()
def cli(
    database: str, payload_store: str
) -> Callable[..., subprocess.CompletedProcess[str]]:
    """Run ``lawgraph <args>`` as a process of its own against the test database."""

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
