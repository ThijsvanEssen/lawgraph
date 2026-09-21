"""``scripts/daily.sh`` and ``scripts/weekly.sh``: what a scheduler runs."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

FAKE_LAWGRAPH = """#!/bin/sh
echo "$*" >> "$CALLS"
case "$*" in "$FAIL_ON"*) exit 1;; esac
exit 0
"""


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """A copy of the scripts next to a `lawgraph` that records what it is asked."""
    shutil.copytree(ROOT / "scripts", tmp_path / "scripts")
    fake = tmp_path / ".venv" / "bin" / "lawgraph"
    fake.parent.mkdir(parents=True)
    fake.write_text(FAKE_LAWGRAPH)
    fake.chmod(0o755)
    return tmp_path


def _run(
    checkout: Path, script: str, fail_on: str = "-"
) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "CALLS": str(checkout / "calls"),
        "FAIL_ON": fail_on,
        "LAWGRAPH_LOG_DIR": str(checkout / "logs"),
        "TMPDIR": str(checkout),
    }
    return subprocess.run(
        ["sh", str(checkout / "scripts" / script)],
        env=env,
        capture_output=True,
        text=True,
    )


def _calls(checkout: Path) -> list[str]:
    return (checkout / "calls").read_text().splitlines()


def test_the_daily_run_is_the_three_phases_since_their_last_complete_run(
    checkout: Path,
) -> None:
    done = _run(checkout, "daily.sh")
    assert done.returncode == 0, done.stderr
    assert _calls(checkout) == [
        "retrieve all --since last",
        "normalize all --since last",
        "semantic all --since last",
        "check --skip-edges",
    ]
    assert (checkout / "logs" / "runs.log").read_text().count("daily.sh: ok") == 1


def test_the_weekly_run_links_everything_before_it_fetches_what_is_missing(
    checkout: Path,
) -> None:
    assert _run(checkout, "weekly.sh").returncode == 0
    assert _calls(checkout) == ["semantic all", "expand-graph", "check"]


def test_a_failing_command_fails_the_run_and_the_rest_still_runs(
    checkout: Path,
) -> None:
    done = _run(checkout, "daily.sh", fail_on="normalize all")
    assert done.returncode == 1
    assert len(_calls(checkout)) == 4  # semantic and check ran too
    runs = (checkout / "logs" / "runs.log").read_text()
    assert "lawgraph normalize all --since last failed" in runs and "FAILED" in runs


def test_two_scheduled_runs_never_write_side_by_side(checkout: Path) -> None:
    (checkout / "lawgraph-scheduled.lock").mkdir()  # the weekly run is still going
    done = _run(checkout, "daily.sh")
    assert done.returncode == 75
    assert not (checkout / "calls").exists()
    assert "not started" in (checkout / "logs" / "runs.log").read_text()


def test_the_lock_is_given_back_also_after_a_failure(checkout: Path) -> None:
    _run(checkout, "daily.sh", fail_on="retrieve all")
    assert not (checkout / "lawgraph-scheduled.lock").exists()
