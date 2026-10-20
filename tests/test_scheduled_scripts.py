"""``scripts/daily.sh`` and ``scripts/weekly.sh``: what a scheduler runs."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.paths import ROOT

FAKE_LAWGRAPH = """#!/bin/sh
echo "$*" >> "$CALLS"
# why it ended so, as the entry point writes it (LAWGRAPH_OUTCOME_FILE)
case "$*" in
  "$FAIL_ON"*) [ -z "$REASON" ] || echo "$REASON" > "$LAWGRAPH_OUTCOME_FILE"; exit 1;;
esac
case "$*" in "$UNAVAILABLE_ON"*) echo "$REASON" > "$LAWGRAPH_OUTCOME_FILE"; exit 3;; esac
# a step that leaves the lock held (a file in it): the next step finds it taken
case "$*" in "$HOLD_ON"*) touch "$TMPDIR/lawgraph-scheduled.lock/held";; esac
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
    # the python of the suite, with lawgraph: it words the alert (python -m lawgraph.alert)
    python = fake.parent / "python"
    python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    python.chmod(0o755)
    return tmp_path


def _run(
    checkout: Path,
    script: str,
    fail_on: str = "-",
    args: list[str] | None = None,
    **extra: str,
) -> subprocess.CompletedProcess:
    # the wait for the lock is the test's own (or the scripts' default), never the one of
    # the environment the suite runs in
    inherited = {k: v for k, v in os.environ.items() if k != "LAWGRAPH_LOCK_WAIT"}
    env = {
        **inherited,
        "UNAVAILABLE_ON": "-",
        "HOLD_ON": "-",
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
        "feed-events",
        "check --skip-edges",
        "search-stats prune",  # the counts of the terms searched, older than a week
        "search-candidates",  # the hits of the words searched most
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
        # the pages of the sitting members of the Eerste Kamer and their periods
        "retrieve eerstekamer-persons --sitting",
        "normalize eerstekamer-persons",
        # every toestand from the SRU listing, which the daily run asks for since a date
        "retrieve bwb-history",
        "semantic all --list",
        "semantic tk",
        # the article citations in slices, until one reads nothing
        "semantic rechtspraak --limit 100000",
        "semantic rechtspraak --after k1 --limit 100000",
        # rechtspraak-citations: left to the daily run (the stubs)
        "semantic bwb-definitions --limit 5000",
        "semantic bwb-definitions --after k1 --limit 5000",
        "semantic graph-heat",
        "expand-graph --no-final-pass",
        "check",
        "search-candidates",
    ]
    # each step took the lock on its own and let it go: a poll can run in between
    runs = (checkout / "logs" / "runs.log").read_text()
    assert runs.count("step.sh: ok") == 14
    assert runs.count("weekly.sh: ok") == 1
    assert not (checkout / "lawgraph-scheduled.lock").exists()


def test_a_failing_weekly_step_is_told_and_the_rest_still_runs(checkout: Path) -> None:
    alerts = checkout / "alerts"
    done = _run(
        checkout,
        "weekly.sh",
        fail_on="semantic tk",
        REASON="DatabaseUnavailable: Cannot connect to PostgreSQL",
        LAWGRAPH_ALERT_COMMAND=f'echo "$LAWGRAPH_ALERT_MESSAGE" >> {alerts}',
    )
    assert done.returncode == 1
    # one alert at the end of the run, with the reason the step gave; not one per step
    assert alerts.read_text().splitlines() == [
        "Wekelijkse update: het koppelen van wetsartikelen in Kamerstukken is mislukt. "
        "De database was niet bereikbaar. Wordt volgende week opnieuw geprobeerd."
    ]
    assert _calls(checkout)[-3:] == [
        "expand-graph --no-final-pass",
        "check",
        "search-candidates",
    ]
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
    # semantic, the events of the feed, check, the prune, the words searched most and
    # sitemaps ran too
    assert len(_calls(checkout)) == 8
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
    assert _calls(checkout) == [
        f"poll {chain} --since {window}",
        "feed-events --days 14",
        "search-candidates",
    ]
    assert "poll.sh: ok" in (checkout / "logs" / "runs.log").read_text()


def test_a_poll_takes_another_window_and_refuses_another_chain(checkout: Path) -> None:
    assert _run(checkout, "poll.sh", args=["tk", "90m"]).returncode == 0
    assert _calls(checkout) == [
        "poll tk --since 90m",
        "feed-events --days 14",
        "search-candidates",
    ]
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

    held = 1.5  # seconds the poll still holds the lock
    lock = checkout / "lawgraph-scheduled.lock"
    lock.mkdir()  # a poll is still going
    threading.Timer(held, lock.rmdir).start()
    began = time.monotonic()
    done = _run(checkout, "daily.sh", LAWGRAPH_LOCK_WAIT="10")
    assert done.returncode == 0, done.stderr
    assert time.monotonic() - began >= held
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
    assert (checkout / "alerts").read_text().splitlines() == [
        "Dagelijkse update: de controle is mislukt. De stap stopte zonder te zeggen "
        "waarom (code 1). Dit vraagt om actie."
    ]


def test_an_alert_that_cannot_be_worded_still_goes(checkout: Path) -> None:
    """Without the python of the app the alert is the record as it is: late, not lost."""
    (checkout / ".venv" / "bin" / "python").unlink()
    alert = f'echo "$LAWGRAPH_ALERT_MESSAGE" >> {checkout / "alerts"}'
    _run(checkout, "daily.sh", fail_on="check", LAWGRAPH_ALERT_COMMAND=alert)
    (message,) = (checkout / "alerts").read_text().splitlines()
    assert message == "lawgraph daily: failed lawgraph check --skip-edges exit code 1"


def test_a_run_that_went_well_alerts_nobody(checkout: Path) -> None:
    alert = f"touch {checkout / 'alerts'}"
    assert _run(checkout, "daily.sh", LAWGRAPH_ALERT_COMMAND=alert).returncode == 0
    assert not (checkout / "alerts").exists()


def test_a_failing_alert_command_does_not_change_the_outcome(checkout: Path) -> None:
    done = _run(checkout, "daily.sh", fail_on="check", LAWGRAPH_ALERT_COMMAND="exit 3")
    assert done.returncode == 1
    assert "the alert command failed" in (checkout / "logs" / "runs.log").read_text()


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
    assert alerts.read_text().splitlines() == [
        "Ophalen van nieuwe stukken van de Tweede Kamer: drie keer achter elkaar niet "
        "gestart, omdat een andere run de database bezet hield. Kijk of die run vastzit."
    ]
    assert _run(checkout, "poll.sh", args=["tk"], **alert).returncode == 75
    assert len(alerts.read_text().splitlines()) == 1  # once, not every time

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


@pytest.mark.parametrize(
    ("repeat", "cap", "failure"),
    [
        # the slice after k1 names k1 again: no step forward
        (
            '*"--after k1"*) echo "go on with --after k1)." >&2;;',
            "",
            "no progress after k1",
        ),
        # every slice goes on: a run over all is far fewer slices than the cap
        (
            '*"--after k"*) echo "go on with --after k$(wc -l < "$CALLS" | tr -d " "))." >&2;;',
            "3",
            "more than 3 slices",
        ),
    ],
)
def test_a_slice_that_does_not_go_on_stops_with_a_failure(
    checkout: Path, repeat: str, cap: str, failure: str
) -> None:
    """A log line that repeats, or a key that does not move, would run the weekly's
    slices for ever: it stops, is told, and the rest of the run goes on."""
    fake = checkout / ".venv" / "bin" / "lawgraph"
    fake.write_text(
        FAKE_LAWGRAPH.replace(
            '*"--after k1"*) echo "The last read was None (go on with --after None)." >&2;;',
            repeat,
        )
    )
    extra = {"MAX_SLICES": cap} if cap else {}
    done = _run(checkout, "weekly.sh", "-", None, **extra)
    assert done.returncode == 1
    assert failure in (checkout / "logs" / "runs.log").read_text()
    assert _calls(checkout)[-3:] == [
        "expand-graph --no-final-pass",
        "check",
        "search-candidates",
    ]


def test_a_run_waits_only_as_long_as_its_test_says(
    checkout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A wait set where the suite runs (the deploy sets one of half an hour) is not the
    scripts': a run that finds the lock held gives its turn up at once."""
    import time

    suite_wait = 30
    monkeypatch.setenv("LAWGRAPH_LOCK_WAIT", str(suite_wait))
    (checkout / "lawgraph-scheduled.lock").mkdir()
    began = time.monotonic()
    assert _run(checkout, "poll.sh", args=["tk"]).returncode == 75
    assert time.monotonic() - began < suite_wait  # it did not wait for the lock


def test_a_failed_step_says_why_in_runs_log_and_the_alert(checkout: Path) -> None:
    """The reason the command gave (``Outcome.reason``) beside its label: the alert alone
    tells what to do, the full text is in the log of the run."""
    alerts = checkout / "alerts"
    why = (
        "DatabaseUnavailable: Cannot connect to PostgreSQL "
        "(Writing a batch of 9 edges failed; it stays queued.)"
    )
    done = _run(
        checkout,
        "daily.sh",
        fail_on="check",
        REASON=why,
        LAWGRAPH_ALERT_COMMAND=f'echo "$LAWGRAPH_ALERT_MESSAGE" >> {alerts}',
    )
    assert done.returncode == 1
    runs = (checkout / "logs" / "runs.log").read_text()
    assert f"lawgraph check --skip-edges failed: {why}" in runs
    assert alerts.read_text().splitlines() == [
        "Dagelijkse update: de controle is mislukt. De database was niet bereikbaar. "
        "Wordt bij de volgende dagelijkse update opnieuw geprobeerd."
    ]


def test_a_step_that_gave_no_reason_is_named_by_its_exit_code(checkout: Path) -> None:
    """Killed, or ended before it could say why."""
    _run(checkout, "daily.sh", fail_on="sitemaps")
    runs = (checkout / "logs" / "runs.log").read_text()
    assert "lawgraph sitemaps failed: exit code 1" in runs


def test_an_unavailable_source_says_which_and_the_run_goes_on(checkout: Path) -> None:
    alerts = checkout / "alerts"
    done = _run(
        checkout,
        "daily.sh",
        REASON="retrieve echr: HUDOC: HTTP 403",
        UNAVAILABLE_ON="retrieve all",
        LAWGRAPH_ALERT_COMMAND=f'echo "$LAWGRAPH_ALERT_MESSAGE" >> {alerts}',
    )
    assert done.returncode == 0 and len(_calls(checkout)) == 8
    runs = (checkout / "logs" / "runs.log").read_text()
    assert (
        "lawgraph retrieve all --since last: a source was unavailable: "
        "retrieve echr: HUDOC: HTTP 403" in runs
    )
    assert alerts.read_text().splitlines() == [
        "Dagelijkse update: ECHR (HUDOC) was niet bereikbaar, de rest is wel bijgewerkt. "
        "Wordt bij de volgende dagelijkse update opnieuw geprobeerd."
    ]


def test_a_skipped_weekly_step_is_in_its_alert(checkout: Path) -> None:
    """A step that waited out its hour for the lock and gave up is told at the end, not only
    in runs.log or after three in a row."""
    alerts = checkout / "alerts"
    done = _run(
        checkout,
        "weekly.sh",
        HOLD_ON="check",
        LAWGRAPH_LOCK_WAIT="0",
        LAWGRAPH_ALERT_COMMAND=f'echo "$LAWGRAPH_ALERT_MESSAGE" >> {alerts}',
    )
    assert done.returncode == 0
    assert _calls(checkout)[-1] == "check"  # search-candidates found the lock held
    assert (
        "weekly.sh: ok, skipped: lawgraph search-candidates"
        in (checkout / "logs" / "runs.log").read_text()
    )
    assert alerts.read_text().splitlines() == [
        "Wekelijkse update: het bijwerken van de zoeksuggesties is overgeslagen, omdat "
        "een andere run de database te lang bezet hield. Wordt volgende week opnieuw "
        "geprobeerd."
    ]
