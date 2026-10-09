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
# the steps of `semantic all`, and a slice that names where to go on, then that it is done
case "$*" in
  "semantic all --list")
    printf '%s\\n' tk rechtspraak rechtspraak-citations bwb-definitions graph-heat;;
  *"--after k1"*) echo "The last read was None (go on with --after None)." >&2;;
  *"--limit"*) echo "The last read was k1 (go on with --after k1)." >&2;;
esac
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
    checkout: Path,
    script: str,
    fail_on: str = "-",
    args: list[str] | None = None,
    **extra: str,
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
        ["sh", str(checkout / "scripts" / script), *(args or [])],
        env=env,
        # the scripts run from cron with nothing on stdin; a fake that reads it waits otherwise
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )


def _calls(checkout: Path) -> list[str]:
    return (checkout / "calls").read_text().splitlines()


def test_the_daily_run_is_the_three_phases_since_their_last_complete_run_and_after(
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
        "sitemaps",
    ]
    assert (checkout / "logs" / "runs.log").read_text().count("daily.sh: ok") == 1


def test_the_weekly_run_links_everything_before_it_fetches_what_is_missing(
    checkout: Path,
) -> None:
    assert _run(checkout, "weekly.sh").returncode == 0
    assert _calls(checkout) == [
        # the members and their seats and vacancies, which the daily run skips
        "retrieve tk-dossiers --since 1d --skip-decisions --skip-documents",
        "normalize tk-dossiers --since 1d",
        "semantic all --list",
        "semantic tk",
        # the article citations in slices, until one reads nothing
        "semantic rechtspraak --limit 100000",
        "semantic rechtspraak --after k1 --limit 100000",
        # rechtspraak-citations: left to the daily run (the stubs)
        "semantic bwb-definitions --limit 5000",
        "semantic bwb-definitions --after k1 --limit 5000",
        "semantic graph-heat",
        "expand-graph",
        "check",
    ]
    # each step took the lock on its own and let it go: a poll can run in between
    runs = (checkout / "logs" / "runs.log").read_text()
    assert runs.count("step.sh: ok") == 10
    assert runs.count("weekly.sh: ok") == 1
    assert not (checkout / "lawgraph-scheduled.lock").exists()


def test_a_failing_weekly_step_is_told_and_the_rest_still_runs(checkout: Path) -> None:
    done = _run(checkout, "weekly.sh", fail_on="semantic tk")
    assert done.returncode == 1
    assert _calls(checkout)[-2:] == ["expand-graph", "check"]
    assert (
        "weekly.sh: FAILED: lawgraph semantic tk"
        in (checkout / "logs" / "runs.log").read_text()
    )


def test_a_weekly_step_waits_for_a_poll_that_holds_the_lock(checkout: Path) -> None:
    """A step waits for a running poll (LAWGRAPH_LOCK_WAIT, an hour by default) instead
    of being skipped: here the lock is let go a second after the run starts."""
    lock = checkout / "lawgraph-scheduled.lock"
    lock.mkdir()
    release = subprocess.Popen(["sh", "-c", f"sleep 1; rmdir {lock}"])
    try:
        assert _run(checkout, "weekly.sh").returncode == 0
    finally:
        release.wait()
    assert _calls(checkout)[0].startswith("retrieve tk-dossiers")


def test_a_failing_command_fails_the_run_and_the_rest_still_runs(
    checkout: Path,
) -> None:
    done = _run(checkout, "daily.sh", fail_on="normalize all")
    assert done.returncode == 1
    assert len(_calls(checkout)) == 6  # semantic, check, the prune and sitemaps ran too
    runs = (checkout / "logs" / "runs.log").read_text()
    assert "lawgraph normalize all --since last failed" in runs and "FAILED" in runs


def test_two_scheduled_runs_never_write_side_by_side(checkout: Path) -> None:
    (checkout / "lawgraph-scheduled.lock").mkdir()  # the weekly run is still going
    done = _run(checkout, "daily.sh")
    assert done.returncode == 75
    assert not (checkout / "calls").exists()
    assert "not started" in (checkout / "logs" / "runs.log").read_text()


@pytest.mark.parametrize(
    ("chain", "window"),
    [("tk", "4h"), ("ek", "4h"), ("rechtspraak", "6h"), ("echr", "1d")],
)
def test_a_poll_reaches_back_past_the_poll_before_it(
    checkout: Path, chain: str, window: str
) -> None:
    done = _run(checkout, "poll.sh", args=[chain])
    assert done.returncode == 0, done.stderr
    assert _calls(checkout) == [f"poll {chain} --since {window}"]
    assert "poll.sh: ok" in (checkout / "logs" / "runs.log").read_text()


def test_a_poll_takes_another_window_and_refuses_another_chain(checkout: Path) -> None:
    assert _run(checkout, "poll.sh", args=["tk", "90m"]).returncode == 0
    assert _calls(checkout) == ["poll tk --since 90m"]
    refused = _run(checkout, "poll.sh", args=["bwb"])
    assert refused.returncode == 2 and "usage" in refused.stderr
    assert not (checkout / "lawgraph-scheduled.lock").exists()


def test_a_poll_leaves_the_database_to_a_run_that_holds_it(checkout: Path) -> None:
    (checkout / "lawgraph-scheduled.lock").mkdir()  # the nightly run is still going
    assert _run(checkout, "poll.sh", args=["tk"]).returncode == 75
    assert not (checkout / "calls").exists()


def test_a_run_may_wait_for_the_lock_and_starts_once_it_is_free(checkout: Path) -> None:
    """The nightly with ``LAWGRAPH_LOCK_WAIT`` waits out a poll that still runs, instead of
    giving the night up."""
    import threading
    import time

    lock = checkout / "lawgraph-scheduled.lock"
    lock.mkdir()  # a poll is still going
    threading.Timer(1.5, lock.rmdir).start()
    began = time.monotonic()
    done = _run(checkout, "daily.sh", LAWGRAPH_LOCK_WAIT="10")
    assert done.returncode == 0, done.stderr
    assert time.monotonic() - began >= 1.5
    assert _calls(checkout)[0] == "retrieve all --since last"
    assert "started after waiting" in (checkout / "logs" / "runs.log").read_text()


def test_a_run_that_waited_long_enough_gives_its_turn_up(checkout: Path) -> None:
    (checkout / "lawgraph-scheduled.lock").mkdir()
    done = _run(checkout, "daily.sh", LAWGRAPH_LOCK_WAIT="2")
    assert done.returncode == 75
    assert not (checkout / "calls").exists()
    assert "not started (waited 2 s)" in (checkout / "logs" / "runs.log").read_text()


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


def test_a_poll_given_up_three_times_in_a_row_says_so_once(checkout: Path) -> None:
    """A long run that keeps the polls out is told after the third poll it kept out, not after
    every one; a poll that runs sets the count back, and each chain counts on its own."""
    alerts = checkout / "alerts"
    alert = {"LAWGRAPH_ALERT_COMMAND": f'echo "$LAWGRAPH_ALERT_MESSAGE" >> {alerts}'}
    lock = checkout / "lawgraph-scheduled.lock"
    lock.mkdir()
    for _ in range(2):
        assert _run(checkout, "poll.sh", args=["tk"], **alert).returncode == 75
    assert _run(checkout, "poll.sh", args=["rechtspraak"], **alert).returncode == 75
    assert not alerts.exists()
    assert _run(checkout, "poll.sh", args=["tk"], **alert).returncode == 75
    assert alerts.read_text().count("skipped 3 times in a row") == 1
    assert "poll tk" in alerts.read_text()
    assert _run(checkout, "poll.sh", args=["tk"], **alert).returncode == 75
    assert (
        alerts.read_text().count("skipped 3 times in a row") == 1
    )  # once, not every time

    lock.rmdir()
    assert _run(checkout, "poll.sh", args=["tk"], **alert).returncode == 0
    assert not (checkout / "logs" / "skipped-poll-tk").exists()
    assert (checkout / "logs" / "skipped-poll-rechtspraak").read_text().strip() == "1"


def test_the_weekly_steps_keep_the_order_of_semantic_all(checkout: Path) -> None:
    """The weekly run takes the steps in the order of ``semantic all --list``, the order of
    the registry, which puts what a step reads before it (``test_semantic_order_puts_what_is
    _read_first``: the linkers before graph-light, bwb before bwb-amendments, …). Only
    rechtspraak-citations is left out; no step after it reads what it would add."""
    from lawgraph.sources.registry import PIPELINES

    names = [pipeline.name for pipeline in PIPELINES["semantic"]]
    fake = checkout / ".venv" / "bin" / "lawgraph"
    listing = " ".join(names)
    fake.write_text(
        FAKE_LAWGRAPH.replace(
            "tk rechtspraak rechtspraak-citations bwb-definitions graph-heat", listing
        )
    )
    assert _run(checkout, "weekly.sh").returncode == 0
    ran = [
        call.split()[1]
        for call in _calls(checkout)
        if call.startswith("semantic ") and call != "semantic all --list"
    ]
    # each step once, the sliced ones per slice
    in_order = list(dict.fromkeys(ran))
    assert in_order == [name for name in names if name != "rechtspraak-citations"]
