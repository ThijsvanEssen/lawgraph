"""The ruff of the dev extra is the ruff of the pre-commit hook: a format from the venv is the
format CI checks."""

from __future__ import annotations

import tomllib

import yaml

from tests.conventions._scan import TESTS

ROOT = TESTS.parent


def test_ruff_is_pinned_to_the_hook() -> None:
    dev = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]["optional-dependencies"]["dev"]
    pinned = [d.split("==", 1)[1] for d in dev if d.startswith("ruff==")]
    repos = yaml.safe_load(
        (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    )["repos"]
    hook = [r["rev"] for r in repos if r["repo"].endswith("/ruff-pre-commit")]
    assert len(pinned) == 1 and hook == [f"v{pinned[0]}"]
