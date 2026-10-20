"""The scripts of ``ops/`` (run on the server through the ops workflow): each parses, each
read-only query it counts with is there, and each script it runs or sources is there."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

from tests.paths import ROOT, python_of_the_suite

OPS = ROOT / "ops"
SCRIPTS = sorted(OPS.glob("*.sh"))


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_a_script_parses(script: Path) -> None:
    done = subprocess.run(["sh", "-n", str(script)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def _named(script: Path) -> tuple[list[str], list[str]]:
    """The queries a script counts with (``counts <block> <before|after> <file.sql>``, also
    inside ``{ …; }``) and the scripts of ops/ it runs or sources (``sh "$D/x.sh"``,
    ``. "$OPS/x.sh"``, ``. "$(dirname "$0")/x.sh"``); its comments left out."""
    lines = script.read_text(encoding="utf-8").splitlines()
    text = "\n".join(ln for ln in lines if not ln.lstrip().startswith("#"))
    queries = re.findall(r"\bcounts \S+ \S+ ([^\s;]+\.sql)\b", text)
    steps = re.findall(r'(?:\bsh|\.) "\$(?:D|OPS|\(dirname "\$0"\))/([^"]+)"', text)
    return queries, steps


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_what_a_script_names_is_there(script: Path) -> None:
    queries, steps = _named(script)
    for name in queries + steps:
        assert (OPS / name).is_file(), name


def test_the_names_are_found() -> None:
    """Both forms of a count on one line, and a chain's step."""
    queries, _ = _named(OPS / "relink-citations-slice.sh")
    assert {"ljn-citations-counts.sql", "citation-paragraphs-counts.sql"} <= set(
        queries
    )
    _, steps = _named(OPS / "staatsblad-notes.sh")
    assert steps == ["_night.sh", "staatsblad-notes-steps.sh"]


@pytest.mark.parametrize("query", sorted(OPS.glob("*.sql")), ids=lambda p: p.name)
def test_a_query_reads_only(query: Path) -> None:
    """Its first statement makes the session read-only, also when run by hand."""
    lines = query.read_text(encoding="utf-8").splitlines()
    first = next(ln.strip() for ln in lines if ln.strip() and not ln.startswith("--"))
    assert first == "SET default_transaction_read_only = on;"


# psql's own rule: a failing statement exits 3 under ON_ERROR_STOP, else the run goes on and exits 0
FAKE_DOCKER = """#!/bin/sh
echo "$@" > "$CALLS"
cat > /dev/null
case " $* " in *" ON_ERROR_STOP=1 "*) echo 'ERROR:  syntax error' >&2; exit 3 ;; esac
exit 0
"""


def test_a_failing_query_fails(tmp_path: Path) -> None:
    """``read_only_sql`` stops at the first failing statement and returns its rc, in a read-only
    session with a time-out, on the container and database of the environment."""
    (tmp_path / "docker").write_text(FAKE_DOCKER, encoding="utf-8")
    (tmp_path / "docker").chmod(0o755)
    calls = tmp_path / "calls"
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "CALLS": str(calls),
        "LAWGRAPH_DB_CONTAINER": "pg-test",
        "LAWGRAPH_DB_NAME": "db_test",
    }
    done = subprocess.run(
        ["sh", "-c", f'. "{OPS}/_sql.sh"; echo "SELEC 1;" | read_only_sql'],
        env=env,
        capture_output=True,
        text=True,
    )
    assert done.returncode == 3, done.stderr
    call = calls.read_text(encoding="utf-8")
    assert "default_transaction_read_only=on" in call
    assert "statement_timeout=600s" in call
    assert " pg-test psql " in call and "-d db_test" in call


PSQL_RUNNERS = [*SCRIPTS, OPS.parent / ".github" / "workflows" / "ops.yml"]


@pytest.mark.parametrize("path", PSQL_RUNNERS, ids=lambda p: p.name)
def test_every_psql_call_stops_at_an_error(path: Path) -> None:
    """psql without ON_ERROR_STOP exits 0 after a failing statement: a red query, a green run."""
    for line in path.read_text(encoding="utf-8").splitlines():
        if re.search(r"\bpsql\b", line) and not line.lstrip().startswith("#"):
            assert "ON_ERROR_STOP=1" in line, line


def test_counts_reads_through_read_only_sql() -> None:
    steps = (OPS / "_steps.sh").read_text(encoding="utf-8")
    assert re.search(r"^counts\(\) \{\n\s+read_only_sql <", steps, re.M)


SERVER = OPS.parent / "deploy" / "server"
REPO_SCRIPTS = OPS.parent / "scripts"


def test_the_server_config_is_there() -> None:
    """What the server runs is kept here: the units, the Caddy block, the alert, apply.sh."""
    for name in (
        "apply.sh",
        "caddy/concordans.caddy",
        "bin/alert.sh",
        "scheduler.env.example",
    ):
        assert (SERVER / name).is_file(), name
    done = subprocess.run(
        ["sh", "-n", str(SERVER / "apply.sh")], capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr


@pytest.mark.parametrize(
    "timer", sorted((SERVER / "systemd").glob("*.timer")), ids=lambda p: p.name
)
def test_a_timer_starts_a_unit_here_that_runs_a_script_in_scripts(timer: Path) -> None:
    """Each timer names a service kept here (``Unit=`` or its own name), and that service runs a
    script of ``scripts/`` from the checkout on the server."""
    text = timer.read_text(encoding="utf-8")
    assert re.search(r"^OnCalendar=.+ Europe/Amsterdam$", text, re.M), "no OnCalendar"
    unit = re.search(r"^Unit=(\S+)$", text, re.M)
    service = unit.group(1) if unit else timer.name.replace(".timer", ".service")
    template = re.sub(r"@[^.]+\.service$", "@.service", service)
    path = SERVER / "systemd" / template
    assert path.is_file(), template
    run = re.search(
        r"^ExecStart=/srv/lawgraph/app/scripts/(\S+)",
        path.read_text(encoding="utf-8"),
        re.M,
    )
    assert run, f"{template} runs no script of scripts/"
    assert (REPO_SCRIPTS / run.group(1)).is_file(), run.group(1)


def test_every_service_but_the_api_is_started_by_a_timer() -> None:
    timers = " ".join(
        p.read_text(encoding="utf-8") + p.name
        for p in (SERVER / "systemd").glob("*.timer")
    )
    for service in (SERVER / "systemd").glob("*.service"):
        if service.name == "lawgraph-api.service":
            continue
        stem = service.name.replace("@.service", "@").replace(".service", "")
        assert stem in timers, service.name


def test_caddy_serves_the_sitemaps_from_where_they_are_written() -> None:
    """``/sitemap*`` is handled before the files of the build and the render route, from the
    directory ``scheduler.env`` gives ``lawgraph sitemaps``, compressed on the way."""
    caddy = (SERVER / "caddy" / "concordans.caddy").read_text(encoding="utf-8")
    env = (SERVER / "scheduler.env.example").read_text(encoding="utf-8")
    where = re.search(r"^LAWGRAPH_SITEMAP_DIR=(\S+)$", env, re.M)
    assert where, "LAWGRAPH_SITEMAP_DIR"
    block = re.search(
        r"handle /sitemap\* \{\s*encode zstd gzip\s*root \* (\S+)\s*file_server\s*\}",
        caddy,
    )
    # plain XML on disk, compressed on the way (``encode``)
    assert block and block.group(1) == where.group(1)
    assert caddy.index("handle /sitemap*") < caddy.index("@file file")
    assert caddy.index("handle /sitemap*") < caddy.index("rewrite * /render")


# ── how a step of an ops script ends ─────────────────────────────────────────

FAKE_STEP = """#!/bin/sh
case "$1" in
  ok) echo "x [INFO] [a] pipelines.command: Done in 1s: 2 created." >&2; exit 0;;
  down) echo "retrieve echr: HUDOC: HTTP 403" > "$LAWGRAPH_OUTCOME_FILE"; exit 3;;
esac
long=$(printf 'word %.0s' $(seq 60))
echo "x [ERROR] [a] pipelines.command: Failed after 3s: SourceDown: $long" >&2
echo "SourceDown: tk down" > "$LAWGRAPH_OUTCOME_FILE"
exit 1
"""


def _function(path: Path, name: str) -> str:
    """The definition of the shell function *name* in *path*: the server's preamble around it
    (scheduler.env, systemctl, the lock) is not there to source."""
    found = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", path.read_text(), re.M | re.S)
    assert found, name
    return found.group(0)


def _app(tmp_path: Path) -> Path:
    """Where the app is on the server: its scripts/_alert.sh, and a python with lawgraph
    (that of this checkout) that words the alert."""
    app = tmp_path / "app"
    (app / "scripts").mkdir(parents=True)
    (app / "scripts" / "_alert.sh").write_text(
        (ROOT / "scripts" / "_alert.sh").read_text()
    )
    python = app / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text(python_of_the_suite())
    python.chmod(0o755)
    return app


def _steps(tmp_path: Path, script: str) -> subprocess.CompletedProcess:
    fake = tmp_path / "lawgraph"
    fake.write_text(FAKE_STEP, encoding="utf-8")
    fake.chmod(0o755)
    alert = f'echo "$LAWGRAPH_ALERT_MESSAGE" >> {tmp_path / "alerts"}'
    env = {**os.environ, "LAWGRAPH_ALERT_COMMAND": alert}
    preamble = (
        f"L={fake}; OUT={tmp_path}\n. scripts/_alert.sh\n"
        f"{_function(OPS / '_steps.sh', 'step')}"
    )
    return subprocess.run(
        ["sh", "-c", preamble + script, "x-steps.sh"],
        env=env,
        cwd=_app(tmp_path),
        capture_output=True,
        text=True,
    )


def test_an_unavailable_source_is_told_and_the_steps_go_on(tmp_path: Path) -> None:
    """Exit 3 is no failure (scripts/_run.sh goes on too): said, alerted, and the next step runs."""
    done = _steps(tmp_path, "step s1 down; step s2 ok; echo after")
    assert done.returncode == 0, done.stdout
    assert done.stdout.rstrip().endswith("after")
    assert (
        "== s1: a source was unavailable (retrieve echr: HUDOC: HTTP 403)"
        in done.stdout
    )
    assert (tmp_path / "alerts").read_text().splitlines() == [
        "Ops x-steps retrieve echr: bron-weg, http-403 [actie]"
    ]


def test_a_failed_step_shows_its_whole_error_and_leaves_its_reason(
    tmp_path: Path,
) -> None:
    """The error line in full (it was cut at 200), and the reason for the alert of `fail`."""
    done = _steps(tmp_path, "step s1 broken; echo the-next")
    assert done.returncode == 1 and "the-next" not in done.stdout
    (line,) = [ln for ln in done.stdout.splitlines() if "Failed after" in ln]
    assert len(line) > 300 and line.endswith("word word ")
    # the record of _alert.sh: what failed, its command line and why
    assert (tmp_path / "failed").read_text() == (
        "failed\tlawgraph broken\tSourceDown: tk down\n"
    )


@pytest.mark.parametrize(
    ("record", "said"),
    [
        (
            "failed\tlawgraph retrieve tk --since 1d\tSourceDown: tk: 10 in a row\n",
            "retrieve tk: mislukt, bron-down",
        ),
        # it failed before a step could say so (the lock, a script that is not there)
        (None, "x-steps: mislukt, exit-1"),
    ],
)
def test_fail_alerts_what_failed(tmp_path: Path, record: str | None, said: str) -> None:
    (tmp_path / "out" / "x-steps").mkdir(parents=True)
    if record:
        (tmp_path / "out" / "x-steps" / "failed").write_text(record)
    alerts = tmp_path / "alerts"
    env = {
        **os.environ,
        "LAWGRAPH_ALERT_COMMAND": f'echo "$LAWGRAPH_ALERT_MESSAGE" >> {alerts}',
    }
    preamble = f"D={tmp_path}; APP={_app(tmp_path)}\n"
    script = f"{preamble}{_function(OPS / '_night.sh', 'fail')}fail x-steps 1"
    done = subprocess.run(["sh", "-c", script, "night-x.sh"], env=env, text=True)
    assert done.returncode == 1
    assert alerts.read_text().splitlines() == [f"Nacht night-x {said} [actie]"]


def _run_log_script() -> str:
    """The script the `run-log` action runs on the server."""
    workflow = (OPS.parent / ".github" / "workflows" / "ops.yml").read_text()
    step = workflow.split("- name: Run log", 1)[1]
    return step.split("<< 'EOF'\n", 1)[1].split("\n          EOF", 1)[0]


def test_run_log_points_an_ops_script_to_log(tmp_path: Path) -> None:
    """Twice on 20 Oct an ops script's name went to `run-log`; it answered with forty file names."""
    (tmp_path / "logs").mkdir()
    (tmp_path / "ops").mkdir()
    (tmp_path / "ops" / "night-07963.log").write_text("x\n")
    env = {
        **os.environ,
        "DEPLOY_DIR": str(tmp_path),
        "OPS_DIR": str(tmp_path / "ops"),
        "NAME": "night-07963",
        "LINES": "5",
    }
    done = subprocess.run(
        ["sh", "-c", _run_log_script()], env=env, capture_output=True, text=True
    )
    assert done.returncode == 1
    assert done.stdout.strip() == (
        "night-07963 is an ops script: its log is action=log (gh workflow run ops "
        "-f action=log -f name=night-07963)"
    )
