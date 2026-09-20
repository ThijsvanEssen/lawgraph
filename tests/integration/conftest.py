"""Integration tests: the real code against a real, deliberately small ArangoDB.

The unit suite runs on fake stores and never executes a query, so what only a server shows
(a result built in its memory, a cursor that is killed, a restart in the middle of a run)
stays invisible there. These tests need the test database of ``docker-compose.yml``::

    docker compose --profile test up -d arangodb-test
    ALLOW_DB_TESTS=1 pytest tests/integration

They never touch the database of ``.env``: they talk to ``LAWGRAPH_TEST_ARANGO_URL`` (default
``http://localhost:8530``) and create and drop databases named ``lawgraph_it_...`` there.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
import requests

TEST_URL = os.environ.get("LAWGRAPH_TEST_ARANGO_URL", "http://localhost:8530")
ROOT = Path(__file__).resolve().parents[2]


def _reachable() -> bool:
    try:
        return requests.get(f"{TEST_URL}/_api/version", timeout=3).status_code in (
            200,
            401,
        )
    except requests.RequestException:
        return False


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if os.environ.get("ALLOW_DB_TESTS") != "1":
        reason = "Integration tests disabled (set ALLOW_DB_TESTS=1 to enable)."
    elif not _reachable():
        reason = (
            f"No test database at {TEST_URL} (docker compose --profile test up -d)."
        )
    else:
        return
    for item in items:
        if "tests/integration" in str(item.fspath):
            item.add_marker(pytest.mark.skip(reason=reason))


@pytest.fixture()
def database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """A fresh database on the test server; ``ArangoStore()`` in this process uses it."""
    from arango.client import ArangoClient

    from lawgraph.config import settings
    from lawgraph.db import store as store_module

    name = f"lawgraph_it_{uuid.uuid4().hex[:10]}"
    monkeypatch.setattr(store_module, "ARANGO_URL", TEST_URL)
    monkeypatch.setattr(store_module, "ARANGO_DB_NAME", name)
    system = ArangoClient(hosts=TEST_URL).db(
        "_system", username=settings.ARANGO_USER, password=settings.ARANGO_PASSWORD
    )
    try:
        yield name
    finally:
        if system.has_database(name):
            system.delete_database(name)


@pytest.fixture()
def cli(database: str) -> Callable[..., subprocess.CompletedProcess[str]]:
    """Run ``lawgraph <args>`` as a process of its own against the test database."""

    def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        env = {
            **os.environ,
            "ARANGO_URL": TEST_URL,
            "ARANGO_DB_NAME": database,
            "LAWGRAPH_LOG_LEVEL": "INFO",
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
