"""What a run does when it is killed: the next run completes the graph."""

from __future__ import annotations

import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from lawgraph.db import GraphStore
from tests.asserts import show_items
from tests.databases import ROOT, lawgraph_env
from tests.integration.graph import collection_counts, edge_keys
from tests.integration.seed import seed

# NodeWriter commits the documents per 500: between the quarter (1,000) and all (4,000) the
# count holds six batches, each far longer (about 0.3 s) than the 50 ms poll.
DOCUMENTS = 4_000


def _start(database: str, payloads: Path, *args: str) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-m", "lawgraph", *args],
        cwd=ROOT,
        env=lawgraph_env(database, payloads),
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
    return collection_counts(store), edge_keys(store)


def test_a_run_that_is_killed_is_completed_by_the_next_run(
    database: str, payloads: Path, cli: Any
) -> None:
    store = GraphStore()
    seed(store, documents=DOCUMENTS, judgments=50, regulations=10)

    run = _start(database, payloads, "normalize", "tk-dossiers")
    _wait_until_halfway(run, store, DOCUMENTS)
    run.send_signal(signal.SIGKILL)
    run.wait(timeout=60)
    partial = collection_counts(store)

    complete, edges = _reference(cli, store)
    assert complete["documents"] == DOCUMENTS
    failing = [name for name in partial if not complete[name] >= partial[name]]
    assert not failing, show_items(failing)

    # And what a clean database makes of the same records is the same graph.
    cli("normalize", "all")
    assert (collection_counts(store), edge_keys(store)) == (complete, edges)
