"""The databases ``tests/pg`` and ``tests/integration`` create on the test server, the store
and the ``lawgraph`` processes pointed at one, and the API serving a store.

Several runs share the test server (agents in worktrees of their own). Every database a run
creates is named after the run: ``lawgraph_it_<checkout>_<pid>_<n>``. A run drops only its own
databases, and at its start the ones a run of the same checkout left behind when it was
killed: those whose process is gone."""

from __future__ import annotations

import itertools
import os
import re
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, NamedTuple

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from lawgraph.db import GraphStore
from lawgraph.db import store as store_module
from lawgraph.db.schema import create_database_sql
from lawgraph.db.store import close_stores

ROOT = Path(__file__).resolve().parents[1]
TEST_URL = os.environ.get(
    "LAWGRAPH_TEST_DB_URL",
    "postgresql://lawgraph:lawgraph-test@localhost:5433/lawgraph",
)
# The server, without a database: the store adds the name.
TEST_SERVER = TEST_URL.rsplit("/", 1)[0]
PREFIX = "lawgraph_it_"
# The checkout the run comes from, as a name may hold it: two worktrees never share one.
CHECKOUT = re.sub(r"[^a-z0-9]+", "_", ROOT.name.lower())[:20]
_numbers = itertools.count(1)


def url_of(name: str) -> str:
    """The URL of database *name* on the test server."""
    return f"{TEST_SERVER}/{name}"


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


def require_test_server(start: str) -> None:
    """Asked for, a test server that does not answer ends the run as failed before any test
    runs; *start* says how to start it. One that answers loses the databases killed runs
    of this checkout left on it."""
    if not asked_for():
        return
    try:
        psycopg.connect(TEST_URL, connect_timeout=3).close()
    except psycopg.OperationalError as error:
        pytest.exit(
            f"ALLOW_DB_TESTS=1, but no PostgreSQL answers at {TEST_URL} ({start}): {error}",
            returncode=1,
        )
    drop_left_behind(TEST_URL)


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


def point_at(
    monkeypatch: pytest.MonkeyPatch, name: str, payloads: Path, **settings: object
) -> None:
    """``GraphStore()`` opens database *name* of the test server, with its payloads in the
    directory *payloads* and the other *settings* of the store module (``DB_POOL_SIZE``,
    ``ALLOW_COLLATION``), until *monkeypatch* undoes it; nothing kept of another database
    is read."""
    from lawgraph.api import warm
    from lawgraph.db import version_cache

    monkeypatch.setattr(store_module, "DB_URL", TEST_SERVER)
    monkeypatch.setattr(store_module, "DB_NAME", name)
    monkeypatch.setattr(store_module, "PAYLOAD_STORE", f"file://{payloads}")
    for setting, value in settings.items():
        monkeypatch.setattr(store_module, setting, value)
    version_cache.clear()
    warm.forget()


@contextmanager
def opened_store() -> Iterator[GraphStore]:
    """A store on the database pointed at, closed at the end of the block."""
    store = GraphStore()
    try:
        yield store
    finally:
        store.close()


class ModuleDatabase(NamedTuple):
    """A database of the tests of a module, and the directory of its payloads."""

    name: str
    payloads: Path


@contextmanager
def module_database(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[ModuleDatabase]:
    """A fresh database for the tests of a module, with payloads of its own, dropped
    afterwards; within the block ``GraphStore()`` opens it."""
    payloads = tmp_path_factory.mktemp("payloads")
    with fresh_database(TEST_URL) as name, pytest.MonkeyPatch.context() as monkeypatch:
        point_at(monkeypatch, name, payloads)
        yield ModuleDatabase(name, payloads)


def lawgraph_env(name: str, payloads: Path) -> dict[str, str]:
    """The environment of a ``lawgraph`` process of its own on database *name* of the test
    server, with its payloads in the directory *payloads*: the code of this checkout, also
    when the installed package is another one."""
    return {
        **os.environ,
        "LAWGRAPH_DB_URL": TEST_SERVER,
        "LAWGRAPH_DB_NAME": name,
        "LAWGRAPH_PAYLOAD_STORE": f"file://{payloads}",
        "PYTHONPATH": str(ROOT / "src"),
        "NO_COLOR": "1",
    }


def lawgraph_runner(
    database: str, payloads: Path
) -> Callable[..., subprocess.CompletedProcess[str]]:
    """``lawgraph <args>`` as a process of its own against *database* on the test server,
    with its payloads in *payloads*: what ``cli`` gives a test, for a fixture of a wider
    scope too."""

    def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        done = subprocess.run(
            [sys.executable, "-m", "lawgraph", *args],
            cwd=ROOT,
            env={**lawgraph_env(database, payloads), "LAWGRAPH_LOG_LEVEL": "INFO"},
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


class Api(TestClient):
    """The test client of the API, and ``get_json`` for an answer a test expects."""

    def get_json(self, path: str, **params: Any) -> Any:
        """The JSON of the answer to ``GET`` *path* with *params* added to its query; any
        status but 200 fails with the URL and the body."""
        __tracebackhide__ = True
        url = httpx.URL(path).copy_merge_params(params)
        response = self.get(url)
        assert response.status_code == 200, (
            f"GET {url} answered {response.status_code}:\n{response.text[:2000]}"
        )
        return response.json()


@contextmanager
def serving(store: object) -> Iterator[Api]:
    """The API answering from *store* within the block; after it, from the real one."""
    from lawgraph.api.app import app
    from lawgraph.api.dependencies import get_store

    app.dependency_overrides[get_store] = lambda: store
    try:
        yield Api(app)
    finally:
        app.dependency_overrides.pop(get_store, None)


# The fixtures of tests/pg and tests/integration (their conftests take them over).


@pytest.fixture()
def payloads(tmp_path: Path) -> Path:
    """The payload store of the test: a directory of its own."""
    return tmp_path / "payloads"


@pytest.fixture()
def database(payloads: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """The name of a fresh database on the test server, dropped afterwards; in the test
    ``GraphStore()`` opens it, with ``payloads``."""
    with fresh_database(TEST_URL) as name:
        point_at(monkeypatch, name, payloads)
        yield name


@pytest.fixture()
def store(database: str) -> Iterator[GraphStore]:
    """The store on ``database``."""
    with opened_store() as opened:
        yield opened


@pytest.fixture()
def api(store: GraphStore) -> Iterator[Api]:
    """The API answering from ``store``."""
    with serving(store) as client:
        yield client
