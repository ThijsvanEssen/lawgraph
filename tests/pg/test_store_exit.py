"""A command that leaves its store open exits quietly: the pool is closed at exit, not by
its finalizer, which cannot join its threads any more and prints a traceback."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tests.databases import lawgraph_env


def test_an_open_store_is_closed_at_exit(
    database: str, payloads: Path, tmp_path: Path
) -> None:
    script = (
        "from lawgraph.db import GraphStore\n"
        "left_open = GraphStore()\n"
        "left_open.query('SELECT 1', {})\n"
        "GraphStore().close()\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", script],
        env=lawgraph_env(database, payloads),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 0, done.stderr
    assert "Traceback" not in done.stderr
