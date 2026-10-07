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
    checkout: Path, script: str, fail_on: str = "-", **extra: str
) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        **extra,
        "CALLS": str(checkout / "calls"),
        "FAIL_ON": fail_on,
        "LAWGRAPH_LOG_DIR": str(checkout / "logs"),
        "TMPDIR": str(checkout),
    }
    return subprocess.run(
        ["sh", str(checkout / "scripts" / script)],
        env=env,
        # the scripts run from cron with nothing on stdin; a fake that reads it waits otherwise
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )


def _calls(checkout: Path) -> list[str]:
    return (checkout / "calls").read_text().splitlines()


def test_the_daily_run_is_the_three_phases_since_their_last_complete_run_and_the_prune(
    checkout: Path,
) -> None:
    done = _run(checkout, "daily.sh")
    assert done.returncode == 0, done.stderr
    assert _calls(checkout) == [
        "retrieve all --since last",
        "normalize all --since last",
        "semantic all --since last",
        "check --skip-edges",
        "search-stats prune",  # the counts of the terms searched, older than a week
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
    assert len(_calls(checkout)) == 5  # semantic, check and the prune ran too
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


def test_a_failed_run_is_alerted_with_what_failed(checkout: Path) -> None:
    alert = f'echo "$LAWGRAPH_ALERT_MESSAGE" >> {checkout / "alerts"}'
    _run(checkout, "daily.sh", fail_on="check", LAWGRAPH_ALERT_COMMAND=alert)
    (message,) = (checkout / "alerts").read_text().splitlines()
    assert "daily.sh" in message and "FAILED: lawgraph check --skip-edges" in message


def test_a_run_that_went_well_alerts_nobody(checkout: Path) -> None:
    alert = f"touch {checkout / 'alerts'}"
    assert _run(checkout, "daily.sh", LAWGRAPH_ALERT_COMMAND=alert).returncode == 0
    assert not (checkout / "alerts").exists()


def test_a_failing_alert_command_does_not_change_the_outcome(checkout: Path) -> None:
    done = _run(checkout, "daily.sh", fail_on="check", LAWGRAPH_ALERT_COMMAND="exit 3")
    assert done.returncode == 1
    assert "the alert command failed" in (checkout / "logs" / "runs.log").read_text()


FAKE_DOCKER_WITHOUT_MOUNT = """#!/bin/sh
echo "docker $*" >> "$CALLS"
exit 0
"""


def _without_backup_mount(checkout: Path) -> dict[str, str]:
    """A `docker` that knows no mount at /backups, and the python that names the database."""
    bin_dir = checkout / "bin"
    bin_dir.mkdir()
    (bin_dir / "docker").write_text(FAKE_DOCKER_WITHOUT_MOUNT)
    (bin_dir / "docker").chmod(0o755)
    python = checkout / ".venv" / "bin" / "python"
    python.write_text("#!/bin/sh\necho lawgraph\n")
    python.chmod(0o755)
    return {"PATH": f"{bin_dir}:{os.environ['PATH']}"}


def test_a_backup_without_its_mount_fails_and_says_how_to_mount_it(
    checkout: Path,
) -> None:
    done = _run(checkout, "backup.sh", **_without_backup_mount(checkout))
    assert done.returncode == 1
    runs = (checkout / "logs" / "runs.log").read_text()
    assert "mounts nothing at /backups" in runs and "dump lawgraph failed" in runs


def test_a_restore_test_without_a_dump_fails(checkout: Path) -> None:
    done = _run(checkout, "restore-test.sh", **_without_backup_mount(checkout))
    assert done.returncode == 1
    assert "no dump of lawgraph" in (checkout / "logs" / "runs.log").read_text()


# A `docker` whose container is this machine: /backups is a directory of the test, and a
# command run in the container runs here with that path put in.
FAKE_DOCKER_LOCAL = """#!/usr/bin/env python3
import os, subprocess, sys
backups = os.environ["BACKUPS"]
args = sys.argv[1:]
if args[0] == "inspect":
    print(backups)
    sys.exit(0)
args = args[1:]  # exec
if args[0] == "-i":
    args = args[1:]
args = [a.replace("/backups", backups) for a in args[1:]]  # without the container
sys.exit(subprocess.run(args).returncode)
"""
# What pg_dump -Fd makes: a directory of mode 0700 with files of mode 0600, whatever the umask.
FAKE_PG_DUMP = """#!/bin/sh
while [ $# -gt 0 ]; do [ "$1" = "-f" ] && dir="$2"; shift; done
mkdir -m 700 "$dir" && echo toc > "$dir/toc.dat" && chmod 600 "$dir/toc.dat"
"""
FAKE_PSQL = """#!/bin/sh
cat > /dev/null
echo "rows dossiers 1"
"""


def test_a_dump_can_be_read_by_whoever_uploads_it(checkout: Path) -> None:
    """pg_dump runs as the container's user and makes the dump readable to it alone; the
    upload command runs as another user on the host, so the dump is opened to every reader."""
    bin_dir, backups = checkout / "bin", checkout / "backups"
    bin_dir.mkdir()
    backups.mkdir()
    for name, body in (
        ("docker", FAKE_DOCKER_LOCAL),
        ("pg_dump", FAKE_PG_DUMP),
        ("psql", FAKE_PSQL),
    ):
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    python = checkout / ".venv" / "bin" / "python"
    python.write_text("#!/bin/sh\necho lawgraph\n")
    python.chmod(0o755)

    done = _run(
        checkout,
        "backup.sh",
        PATH=f"{bin_dir}:{os.environ['PATH']}",
        BACKUPS=str(backups),
    )
    assert done.returncode == 0, (checkout / "logs" / "runs.log").read_text()
    (dump,) = backups.iterdir()
    assert not dump.name.endswith(".partial")
    assert dump.stat().st_mode & 0o005 == 0o005  # others may list and enter it
    for paper in dump.iterdir():
        assert paper.stat().st_mode & 0o004, paper.name  # and read every file
