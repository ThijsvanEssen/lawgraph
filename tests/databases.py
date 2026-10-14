"""The databases ``tests/pg`` and ``tests/integration`` create on the test server.

Several runs share the test server (agents in worktrees of their own). Every database a run
creates is named after the run: ``lawgraph_it_<checkout>_<pid>_<n>``. A run drops only its own
databases, and at its start the ones a run of the same checkout left behind when it was
killed: those whose process is gone."""

from __future__ import annotations

import itertools
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import psycopg
import pytest

from lawgraph.db.schema import create_database_sql
from lawgraph.db.store import close_stores

PREFIX = "lawgraph_it_"
# The checkout the run comes from, as a name may hold it: two worktrees never share one.
CHECKOUT = re.sub(r"[^a-z0-9]+", "_", Path(__file__).resolve().parents[1].name.lower())[
    :20
]
_numbers = itertools.count(1)


def run_prefix(pid: int | None = None) -> str:
    """The start of the name of every database of the run of process *pid* (this one by
    default) from this checkout."""
    return f"{PREFIX}{CHECKOUT}_{os.getpid() if pid is None else pid}_"


def new_database_name() -> str:
    """A name for a database of this run, used by no other."""
    return f"{run_prefix()}{next(_numbers)}"


@contextmanager
def fresh_database(admin_url: str) -> Iterator[str]:
    """The name of a fresh database on the server of *admin_url*, dropped afterwards. The
    stores a test left open on it are closed first: their pools would go on reconnecting
    to it and log to the output of a test long over."""
    name = new_database_name()
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(create_database_sql(name).encode())
        try:
            yield name
        finally:
            close_stores(name)
            admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)'.encode())


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def drop_left_behind(admin_url: str) -> list[str]:
    """Drop the databases of the runs of this checkout whose process is gone (a run that
    was killed before it could drop them); return their names."""
    own = re.compile(rf"{re.escape(PREFIX)}{re.escape(CHECKOUT)}_(\d+)_\d+")
    with psycopg.connect(admin_url, autocommit=True) as admin:
        names = [
            name
            for (name,) in admin.execute("SELECT datname FROM pg_database").fetchall()
        ]
        dropped = []
        for name in names:
            found = own.fullmatch(name)
            if found and not _alive(int(found.group(1))):
                admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'.encode())
                dropped.append(name)
    return dropped


def asked_for() -> bool:
    """Whether ``ALLOW_DB_TESTS=1`` asks for the tests against the test server."""
    return os.environ.get("ALLOW_DB_TESTS") == "1"


def require_test_server(url: str, start: str) -> None:
    """Asked for, a test server at *url* that does not answer ends the run as failed before
    any test runs; *start* says how to start it. One that answers loses the databases
    killed runs of this checkout left on it."""
    if not asked_for():
        return
    try:
        psycopg.connect(url, connect_timeout=3).close()
    except psycopg.OperationalError as error:
        pytest.exit(
            f"ALLOW_DB_TESTS=1, but no PostgreSQL answers at {url} ({start}): {error}",
            returncode=1,
        )
    drop_left_behind(url)


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
