"""The tools have one version each. The ruff of the dev extra is the ruff of the pre-commit hook:
a format from the venv is the format CI checks. The uv of the dev extra is the uv the workflows
set up, and uv.lock is the lock of pyproject.toml: CI and the deploy install from it
(``uv sync --frozen``), so a dependency changed without ``uv lock`` would go unnoticed."""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import yaml

from tests.paths import TESTS

ROOT = TESTS.parent
WORKFLOWS = ROOT / ".github" / "workflows"


def _pinned(name: str) -> str:
    dev = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]["optional-dependencies"]["dev"]
    pinned = [d.split("==", 1)[1].split()[0] for d in dev if d.startswith(f"{name}==")]
    assert len(pinned) == 1, f"{name} is not pinned with == in the dev extra"
    return pinned[0]


def test_ruff_is_pinned_to_the_hook() -> None:
    repos = yaml.safe_load(
        (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    )["repos"]
    hook = [r["rev"] for r in repos if r["repo"].endswith("/ruff-pre-commit")]
    assert hook == [f"v{_pinned('ruff')}"]


def test_workflows_set_up_the_uv_of_the_dev_extra() -> None:
    versions = {
        f"{path.name}: {step['with'].get('version')}"
        for path in sorted(WORKFLOWS.glob("*.y*ml"))
        for job in yaml.safe_load(path.read_text(encoding="utf-8"))["jobs"].values()
        for step in job.get("steps", [])
        if str(step.get("uses", "")).startswith("astral-sh/setup-uv@")
    }
    assert versions
    assert {v for v in versions if not v.endswith(f": {_pinned('uv')}")} == set()


def test_the_lock_is_the_lock_of_pyproject() -> None:
    uv = Path(sys.executable).with_name("uv")
    done = subprocess.run(
        [str(uv), "lock", "--check", "--offline"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, f"run `uv lock`:\n{done.stderr}"
