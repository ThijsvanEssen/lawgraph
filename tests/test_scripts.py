"""The scripts a timer or an operator runs by their path are executable in git.

A script that is mode 100644 in the repository is checked out without its execute bit, and
a systemd timer that calls it by its path stops with "Permission denied" (rc 126): so did
``scripts/backup.sh`` on the server. A script whose name starts with ``_`` is sourced by the
others, not run.
"""

from __future__ import annotations

import pathlib
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _modes() -> dict[str, str]:
    try:
        listed = subprocess.run(
            ["git", "ls-files", "-s", "--", "scripts/*.sh"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    return {line.split("\t")[1]: line.split()[0] for line in listed.splitlines()}


def test_every_script_that_is_run_is_executable_in_git() -> None:
    modes = _modes()
    assert modes, "no scripts/*.sh in git"
    run = {
        path: mode
        for path, mode in modes.items()
        if not pathlib.PurePath(path).name.startswith("_")
    }
    assert {path for path, mode in run.items() if mode != "100755"} == set()
