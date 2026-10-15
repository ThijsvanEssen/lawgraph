"""The databases of a run on the shared test server: a dropped one takes the stores a test
left open on it along; every database belongs to the run that made it, and another run,
alive or killed, is only cleaned up after when it was killed."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
from pathlib import Path

import psycopg
import pytest

from lawgraph.db import GraphStore, request_context
from lawgraph.db import store as store_module
from tests.databases import drop_left_behind, fresh_database, run_prefix
from tests.pg.conftest import TEST_URL

ROOT = Path(__file__).resolve().parents[2]
# Another run: it makes a database, says its name and holds it until it is killed.
OTHER_RUN = """
import sys, time
from tests.databases import fresh_database
with fresh_database(sys.argv[1]) as name:
    print(name, flush=True)
    time.sleep(600)
"""


def _databases() -> set[str]:
    with psycopg.connect(TEST_URL) as admin:
        return {name for (name,) in admin.execute("SELECT datname FROM pg_database")}


def test_no_pool_of_a_dropped_test_database_goes_on_reconnecting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with fresh_database(TEST_URL) as name:
        monkeypatch.setattr(store_module, "DB_URL", TEST_URL.rsplit("/", 1)[0])
        monkeypatch.setattr(store_module, "DB_NAME", name)
        monkeypatch.setattr(
            store_module, "PAYLOAD_STORE", f"file://{tmp_path / 'payloads'}"
        )
        left_open = GraphStore()
        with request_context.in_background():
            assert list(left_open.query("SELECT 1")) == [1]
        assert left_open._background_pool is not None
    assert left_open.pool.closed
    assert left_open._background_pool.closed
    assert not [
        thread.name
        for thread in threading.enumerate()
        if thread.name.startswith("lawgraph-background")
    ]


def test_a_run_keeps_the_database_of_a_live_run_and_drops_that_of_a_killed_one() -> (
    None
):
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), str(ROOT)])}
    other = subprocess.Popen(
        [sys.executable, "-c", OTHER_RUN, TEST_URL],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert other.stdout is not None
        theirs = other.stdout.readline().strip()
        with fresh_database(TEST_URL) as ours:
            assert ours.startswith(run_prefix())
            assert theirs.startswith(run_prefix(other.pid))
            assert drop_left_behind(TEST_URL) == []
            assert {ours, theirs} <= _databases()
            other.send_signal(signal.SIGKILL)
            other.wait(timeout=30)
            assert drop_left_behind(TEST_URL) == [theirs]
            assert ours in _databases()
        assert theirs not in _databases()
    finally:
        other.kill()
        other.wait(timeout=30)
