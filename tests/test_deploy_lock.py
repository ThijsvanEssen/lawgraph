"""The deploy and its rollback wait for a scheduled run that holds the lock.

The part of each step of ``.github/workflows/deploy.yml`` that takes the lock (from ``LOCK=``
to its ``trap``) is taken out of the workflow and run against a lock directory of its own.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "deploy.yml"


def _lock_part(step: str) -> str:
    lines = WORKFLOW.read_text().splitlines()
    start = lines.index(f"      - name: {step}")
    begin = next(
        i for i in range(start, len(lines)) if lines[i].strip().startswith("LOCK=")
    )
    end = next(
        i
        for i in range(begin, len(lines))
        if lines[i].strip() == "trap 'rmdir \"$LOCK\"' EXIT"
    )
    return "\n".join(line[10:] for line in lines[begin : end + 1])


def _take(tmp_path: Path, step: str, wait: int) -> subprocess.CompletedProcess:
    script = "\n".join(
        [
            "set -e",
            'alert() { echo "ALERT $1"; }',
            _lock_part(step),
            'echo "HELD $(test -d "$LOCK" && echo yes)"',
        ]
    )
    return subprocess.run(
        ["sh", "-c", script],
        env={
            **os.environ,
            "DEPLOY_DIR": str(tmp_path),
            "SHA": "abcdef0123456789",
            "LAWGRAPH_LOCK_WAIT": str(wait),
        },
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.fixture
def lock(tmp_path: Path) -> Path:
    (tmp_path / "tmp").mkdir()
    return tmp_path / "tmp" / "lawgraph-scheduled.lock"


@pytest.mark.parametrize("step", ["Deploy", "Roll back"])
def test_a_free_lock_is_taken_and_given_back(
    tmp_path: Path, lock: Path, step: str
) -> None:
    done = _take(tmp_path, step, wait=5)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "HELD yes" in done.stdout
    assert "waiting" not in done.stdout
    assert not lock.exists()


@pytest.mark.parametrize("step", ["Deploy", "Roll back"])
def test_it_waits_for_a_run_that_lets_the_lock_go(
    tmp_path: Path, lock: Path, step: str
) -> None:
    lock.mkdir()
    release = subprocess.Popen(["sh", "-c", f"sleep 2; rmdir '{lock}'"])
    try:
        done = _take(tmp_path, step, wait=20)
    finally:
        release.wait()
    assert done.returncode == 0, done.stdout + done.stderr
    assert (
        "a scheduled run holds" in done.stdout
        and "waiting (0 s of 20 s)" in done.stdout
    )
    assert "after waiting" in done.stdout and "HELD yes" in done.stdout
    assert not lock.exists()


@pytest.mark.parametrize("step", ["Deploy", "Roll back"])
def test_a_lock_still_held_after_the_wait_fails(
    tmp_path: Path, lock: Path, step: str
) -> None:
    lock.mkdir()
    done = _take(tmp_path, step, wait=2)
    assert done.returncode == 1
    assert "still holds" in done.stdout and "HELD" not in done.stdout
    # the rollback also says so through the alert; the lock of the run stays its own
    assert ("ALERT" in done.stdout) == (step == "Roll back")
    assert lock.is_dir()


def test_only_the_deploy_job_waits_for_the_lock() -> None:
    """The wait is set on the deploy job alone: the test job runs the suite, whose scheduled
    scripts would wait as long for every lock a test holds."""
    lines = WORKFLOW.read_text().splitlines()
    (setting,) = [i for i, line in enumerate(lines) if "LAWGRAPH_LOCK_WAIT:" in line]
    jobs = [i for i, line in enumerate(lines) if line in ("  test:", "  deploy:")]
    assert lines[max(i for i in jobs if i < setting)] == "  deploy:"
