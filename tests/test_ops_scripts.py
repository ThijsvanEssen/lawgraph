"""The scripts of ``ops/`` (run on the server through the ops workflow): each parses, each
read-only query it counts with is there, and each step a chain runs is a script of its own."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1] / "ops"
SCRIPTS = sorted(OPS.glob("*.sh"))


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_a_script_parses(script: Path) -> None:
    done = subprocess.run(["sh", "-n", str(script)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_what_a_script_names_is_there(script: Path) -> None:
    text = script.read_text(encoding="utf-8")
    for query in re.findall(r"^\s*counts \S+ \S+ (\S+\.sql)", text, re.M):
        assert (OPS / query).is_file(), query
    for chain in re.findall(r"^for s in ([^;]+); do", text, re.M):
        for step in chain.split():
            assert (OPS / f"{step}.sh").is_file(), step


def test_the_backfill_steps_hand_on_their_moment() -> None:
    """Step 1 keeps the moment it began; step 2 normalizes since then, and refuses to run
    without it."""
    first = (OPS / "revises-1-retrieve.sh").read_text(encoding="utf-8")
    second = (OPS / "revises-2-normalize.sh").read_text(encoding="utf-8")
    assert (
        'out/revises-backfill.since"' in first
        and "retrieve tk --replacing --mode full" in first
    )
    assert 'normalize tk --since "$since"' in second and "exit 1" in second


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
