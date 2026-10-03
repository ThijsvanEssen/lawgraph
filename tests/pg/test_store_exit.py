"""A command that leaves its store open exits quietly: the pool is closed at exit, not by
its finalizer, which cannot join its threads any more and prints a traceback."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import lawgraph


def test_an_open_store_is_closed_at_exit(database_url: str, tmp_path: Path) -> None:
    server, name = database_url.rsplit("/", 1)
    env = {
        **os.environ,
        "LAWGRAPH_DB_URL": server,
        "LAWGRAPH_DB_NAME": name,
        "LAWGRAPH_PAYLOAD_STORE": f"file://{tmp_path / 'payloads'}",
        # the code under test, wherever the child starts
        "PYTHONPATH": str(Path(lawgraph.__file__).parents[1]),
    }
    script = (
        "from lawgraph.db import GraphStore\n"
        "left_open = GraphStore()\n"
        "left_open.query('SELECT 1', {})\n"
        "GraphStore().close()\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 0, done.stderr
    assert "Traceback" not in done.stderr
