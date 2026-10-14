"""One version: ``lawgraph.__version__``. The package, the API and the smoke test of the
deploy all take it from there."""

from __future__ import annotations

import os
import shutil
import subprocess
import tomllib

import lawgraph
from lawgraph.api.app import app
from tests.paths import ROOT

WORKFLOW = ROOT / ".github" / "workflows" / "deploy.yml"


def test_the_package_takes_its_version_from_lawgraph() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert "version" not in project["project"]
    assert project["project"]["dynamic"] == ["version"]
    assert project["tool"]["setuptools"]["dynamic"]["version"] == {
        "attr": "lawgraph.__version__"
    }


def test_the_api_reports_that_version() -> None:
    assert app.version == lawgraph.__version__


def _smoke_step() -> str:
    lines = WORKFLOW.read_text().splitlines()
    start = lines.index("      - name: Smoke test")
    begin = lines.index("        run: |", start) + 1
    end = next(i for i in range(begin, len(lines)) if not lines[i].startswith(" " * 10))
    return "\n".join(line[10:] for line in lines[begin:end])


def test_the_deploy_gives_the_smoke_test_the_version_of_its_checkout(tmp_path) -> None:
    (tmp_path / "src" / "lawgraph").mkdir(parents=True)
    shutil.copy(
        ROOT / "src" / "lawgraph" / "__init__.py", tmp_path / "src" / "lawgraph"
    )
    (tmp_path / "scripts").mkdir()
    stub = tmp_path / "scripts" / "smoke.sh"
    stub.write_text('#!/bin/sh\necho "smoke $1 $2"\n')
    stub.chmod(0o755)
    run = subprocess.run(
        ["sh", "-e", "-c", _smoke_step()],
        cwd=tmp_path,
        env={**os.environ, "PUBLIC_URL": "https://example.test"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    assert run.stdout.strip() == f"smoke https://example.test {lawgraph.__version__}"
