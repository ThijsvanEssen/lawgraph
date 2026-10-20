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

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.db import GraphStore, request_context
from tests.databases import (
    TEST_URL,
    Api,
    drop_left_behind,
    fresh_database,
    point_at,
    run_prefix,
    serving,
)
from tests.pg.committee_graph import authorship_graph

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
        point_at(monkeypatch, name, tmp_path / "payloads")
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


# Two tests one after the other, each on a database of its own: each reads its own graph.


def test_the_dossiers_of_a_faction_come_from_the_database_of_the_test(
    store: GraphStore, api: Api
) -> None:
    authorship_graph(store)
    assert api.get_json("/api/factions/vvd/dossiers")["total"] == 1


def test_the_same_faction_on_another_database_has_dossiers_of_its_own(
    store: GraphStore, api: Api
) -> None:
    store.bulk_insert_or_update_nodes(
        "factions",
        [{"key": "vvd", "type": "faction", "labels": [], "props": {"name": "VVD"}}],
    )
    assert api.get_json("/api/factions/vvd/dossiers")["total"] == 0


def test_no_store_is_served_after_the_test_that_served_one() -> None:
    assert app.dependency_overrides == {}


def test_the_api_serves_a_store_only_while_it_is_served(store: GraphStore) -> None:
    with serving(store) as client:
        assert app.dependency_overrides[get_store]() is store
        with pytest.raises(AssertionError, match="/api/factions/nobody"):
            client.get_json("/api/factions/nobody")
    assert get_store not in app.dependency_overrides
