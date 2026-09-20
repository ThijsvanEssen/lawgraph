"""What a run does when the database restarts under it, or when the run itself is killed."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from typing import Any

import pytest

from lawgraph.db import ArangoStore
from tests.integration.conftest import ROOT, TEST_URL
from tests.integration.seed import seed
from tests.integration.test_chain import _counts, _edge_keys

CONTAINER = "arango-lawgraph-test"
DOCUMENTS = 20_000


def _docker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=120
    )


@pytest.fixture()
def container() -> str:
    if _docker("inspect", CONTAINER).returncode != 0:
        pytest.skip(
            f"the fault tests restart the container {CONTAINER}; it is not there"
        )
    return CONTAINER


def _start(database: str, *args: str) -> subprocess.Popen[str]:
    env = {
        **os.environ,
        "ARANGO_URL": TEST_URL,
        "ARANGO_DB_NAME": database,
        "NO_COLOR": "1",
    }
    return subprocess.Popen(
        [sys.executable, "-m", "lawgraph", *args],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _wait_until_halfway(
    run: subprocess.Popen[str], store: ArangoStore, documents: int
) -> None:
    """Return when the run has written part of its documents (and is still running)."""
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        written = store.db.collection("documents").count()
        if written >= documents // 4:
            assert run.poll() is None, (
                "the run ended before the fault could be injected"
            )
            assert written < documents, "the run had written everything already"
            return
        assert run.poll() is None, (
            "the run ended before it wrote a quarter of its documents"
        )
        time.sleep(0.05)
    raise AssertionError("the run did not get going")


def _reference(cli: Any, store: ArangoStore) -> tuple[dict[str, int], set[str]]:
    cli("normalize", "all")
    return _counts(store), _edge_keys(store)


def test_a_database_that_restarts_in_the_middle_costs_a_rerun_at_most(
    database: str, cli: Any, container: str
) -> None:
    """The run rides it out or fails loudly; after a re-run the graph is the complete one."""
    store = ArangoStore()
    seed(store, documents=DOCUMENTS, judgments=50, regulations=10)

    run = _start(database, "normalize", "tk-dossiers")
    _wait_until_halfway(run, store, DOCUMENTS)
    assert _docker("restart", "-t", "0", container).returncode == 0
    output, _ = run.communicate(timeout=900)

    # Either the writes were sent again and it finished, or it says that it failed: never a
    # "success" that left things out.
    assert run.returncode in (0, 1), output[-2000:]
    if run.returncode == 1:
        assert "[ERROR]" in output
    print(
        f"\nrestart in the middle: exit {run.returncode}\n"
        + "\n".join(
            line[24:190]
            for line in output.splitlines()
            if "WARNING" in line or "ERROR" in line
        )
    )
    interrupted = _counts(ArangoStore())

    cli("normalize", "all")
    after_rerun = (_counts(store), _edge_keys(store))

    # The same data in a database that was never disturbed.
    assert after_rerun[0]["documents"] == DOCUMENTS and after_rerun[0]["decisions"] > 0
    assert all(after_rerun[0][name] >= interrupted[name] for name in interrupted)
    cli("normalize", "all")
    assert (_counts(store), _edge_keys(store)) == after_rerun


def test_a_run_that_is_killed_is_completed_by_the_next_run(
    database: str, cli: Any
) -> None:
    store = ArangoStore()
    seed(store, documents=DOCUMENTS, judgments=50, regulations=10)

    run = _start(database, "normalize", "tk-dossiers")
    _wait_until_halfway(run, store, DOCUMENTS)
    run.send_signal(signal.SIGKILL)
    run.wait(timeout=60)
    partial = _counts(store)

    complete, edges = _reference(cli, store)
    assert complete["documents"] == DOCUMENTS
    assert all(complete[name] >= partial[name] for name in partial)

    # And what a clean database makes of the same records is the same graph.
    cli("normalize", "all")
    assert (_counts(store), _edge_keys(store)) == (complete, edges)
