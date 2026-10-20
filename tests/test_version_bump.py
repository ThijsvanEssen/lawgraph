"""``.github/scripts/version-bump.sh BASE``: HEAD differs from BASE in nothing but a higher
version, in its two places (``__version__`` and the ``version`` of docs/openapi.json). Such a
commit takes the green run of BASE instead of running the suites (tested-before.sh).

The diffs of the bump pull requests #809 and #824 are in tests/fixtures as they were."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from tests.paths import ROOT

SCRIPT = ROOT / ".github" / "scripts" / "version-bump.sh"
FIXTURES = ROOT / "tests" / "fixtures"
INIT = "src/lawgraph/__init__.py"
OPENAPI = "docs/openapi.json"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _with_version(text: str, version: str) -> str:
    """*text* (``__init__.py`` or openapi.json) at *version*."""
    text = re.sub(
        r'^__version__ = ".*"$', f'__version__ = "{version}"', text, flags=re.M
    )
    return re.sub(
        r'^(    "version": )".*",$', rf'\g<1>"{version}",', text, count=1, flags=re.M
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository with the two files of the version at 0.79.64, committed as BASE."""
    for name in (INIT, OPENAPI):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(
            _with_version((ROOT / name).read_text(), "0.79.64")
        )
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", ".")
    _git(
        tmp_path,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "commit",
        "-qm",
        "base",
    )
    _git(tmp_path, "tag", "base")
    return tmp_path


def _commit(repo: Path) -> None:
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "head")


def _apply(repo: Path, diff: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "apply", "-"], input=diff, text=True, check=True
    )
    _commit(repo)


def _bump(repo: Path) -> bool:
    done = subprocess.run(
        ["sh", str(SCRIPT), "base"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert done.returncode in (0, 1), done.stderr
    return done.returncode == 0


def test_the_bump_of_809_is_a_bump(repo: Path) -> None:
    _apply(repo, (FIXTURES / "bump_809.diff").read_text())
    assert _bump(repo)


def test_the_bump_of_824_is_a_bump(repo: Path) -> None:
    _apply(repo, (FIXTURES / "bump_809.diff").read_text())
    _git(repo, "tag", "-f", "base")
    _apply(repo, (FIXTURES / "bump_824.diff").read_text())
    assert _bump(repo)


def test_a_bump_with_one_line_more_is_not(repo: Path) -> None:
    _apply(repo, (FIXTURES / "bump_809.diff").read_text())
    init = repo / INIT
    init.write_text(init.read_text() + "DEBUG = True\n")
    _commit(repo)
    assert not _bump(repo)


def test_a_bump_with_another_file_is_not(repo: Path) -> None:
    _apply(repo, (FIXTURES / "bump_809.diff").read_text())
    (repo / "README.md").write_text("more\n")
    _commit(repo)
    assert not _bump(repo)


def test_another_line_of_openapi_is_not(repo: Path) -> None:
    _apply(repo, (FIXTURES / "bump_809.diff").read_text())
    openapi = repo / OPENAPI
    openapi.write_text(openapi.read_text().replace('"calls": 200', '"calls": 201', 1))
    _commit(repo)
    assert not _bump(repo)


@pytest.mark.parametrize(
    ("init", "openapi"),
    [
        ("0.79.63", "0.79.63"),  # down
        ("0.79.65", "0.79.66"),  # two versions
        ("0.79.65", "0.79.64"),  # one place only
    ],
)
def test_a_version_not_higher_in_both_places_is_not(
    repo: Path, init: str, openapi: str
) -> None:
    (repo / INIT).write_text(_with_version((repo / INIT).read_text(), init))
    (repo / OPENAPI).write_text(_with_version((repo / OPENAPI).read_text(), openapi))
    _commit(repo)
    assert not _bump(repo)


def test_a_higher_minor_version_is_a_bump(repo: Path) -> None:
    for name in (INIT, OPENAPI):
        (repo / name).write_text(_with_version((repo / name).read_text(), "0.80.0"))
    _commit(repo)
    assert _bump(repo)


def test_no_change_is_not_a_bump(repo: Path) -> None:
    _git(
        repo,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "x",
    )
    assert not _bump(repo)
