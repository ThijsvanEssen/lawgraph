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
