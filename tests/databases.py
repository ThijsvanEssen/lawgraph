"""The databases ``tests/pg`` and ``tests/integration`` create on the test server."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg

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
