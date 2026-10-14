"""``ALLOW_DB_TESTS=1`` asks for the database suites: a test server that does not answer then
fails the run instead of skipping every test in it. Without the switch they are skipped."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NO_SERVER = "postgresql://nobody@127.0.0.1:1/nothing"
SUITES = ["tests/pg/test_test_databases.py", "tests/integration/test_stubs.py"]


def _pytest(*suites: str, **switches: str) -> subprocess.CompletedProcess[str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"ALLOW_DB_TESTS", "ALLOW_S3_TESTS", "PYTEST_XDIST_WORKER"}
    }
    env["LAWGRAPH_TEST_DB_URL"] = NO_SERVER
    env.update(switches)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", *suites],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.mark.parametrize("suite", SUITES)
def test_a_requested_database_that_does_not_answer_fails_the_run(suite: str) -> None:
    done = _pytest(suite, ALLOW_DB_TESTS="1")
    assert done.returncode != 0, done.stdout
    assert f"no PostgreSQL answers at {NO_SERVER}" in done.stdout + done.stderr


def test_without_the_switch_the_database_suites_are_skipped() -> None:
    done = _pytest(*SUITES)
    assert done.returncode == 0, done.stdout
    assert f"{len(SUITES)} skipped" in done.stdout
