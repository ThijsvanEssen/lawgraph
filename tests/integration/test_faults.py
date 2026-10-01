"""What a run does when it is killed: the next run completes the graph."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from typing import Any

from lawgraph.db import GraphStore
from tests.integration.conftest import ROOT, TEST_SERVER
from tests.integration.seed import seed
from tests.integration.test_chain import _counts, _edge_keys

DOCUMENTS = 20_000


def _start(database: str, payload_store: str, *args: str) -> subprocess.Popen[str]:
    env = {
        **os.environ,
        "LAWGRAPH_DB_URL": TEST_SERVER,
        "LAWGRAPH_DB_NAME": database,
        "LAWGRAPH_PAYLOAD_STORE": payload_store,
        "PYTHONPATH": str(ROOT / "src"),
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
    run: subprocess.Popen[str], store: GraphStore, documents: int
) -> None:
    """Return when the run has written part of its documents (and is still running)."""
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        written = store.count("documents")
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


def _reference(cli: Any, store: GraphStore) -> tuple[dict[str, int], set[str]]:
    cli("normalize", "all")
    return _counts(store), _edge_keys(store)


def test_a_run_that_is_killed_is_completed_by_the_next_run(
    database: str, payload_store: str, cli: Any
) -> None:
    store = GraphStore()
    seed(store, documents=DOCUMENTS, judgments=50, regulations=10)

    run = _start(database, payload_store, "normalize", "tk-dossiers")
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
