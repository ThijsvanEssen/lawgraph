"""The databases ``tests/pg`` and ``tests/integration`` create on the test server."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
import pytest

from lawgraph.db.schema import create_database_sql
from lawgraph.db.store import close_stores


@contextmanager
def fresh_database(admin_url: str) -> Iterator[str]:
    """The name of a fresh database on the server of *admin_url*, dropped afterwards. The
    stores a test left open on it are closed first: their pools would go on reconnecting
    to it and log to the output of a test long over."""
    name = f"lawgraph_it_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(create_database_sql(name).encode())
        try:
            yield name
        finally:
            close_stores(name)
            admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)'.encode())


def asked_for() -> bool:
    """Whether ``ALLOW_DB_TESTS=1`` asks for the tests against the test server."""
    return os.environ.get("ALLOW_DB_TESTS") == "1"


def require_test_server(url: str, start: str) -> None:
    """Asked for, a test server at *url* that does not answer ends the run as failed before
    any test runs; *start* says how to start it."""
    if not asked_for():
        return
    try:
        psycopg.connect(url, connect_timeout=3).close()
    except psycopg.OperationalError as error:
        pytest.exit(
            f"ALLOW_DB_TESTS=1, but no PostgreSQL answers at {url} ({start}): {error}",
            returncode=1,
        )


def skip_unless_asked_for(items: list[pytest.Item], directory: str) -> None:
    """Not asked for, the tests under *directory* are skipped."""
    if asked_for():
        return
    skip = pytest.mark.skip(
        reason="Database tests disabled (set ALLOW_DB_TESTS=1 to enable)."
    )
    for item in items:
        if directory in str(item.fspath):
            item.add_marker(skip)
