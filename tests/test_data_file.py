"""A data file built from stored records: ``build`` writes it and ``check`` fails on a
difference, both printing what changed."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from lawgraph.commands import _data_file
from lawgraph.commands._data_file import build_or_check, keyed_differences

BEFORE = [
    {"code": "HR", "name": "Hoge Raad"},
    {"code": "RVS", "name": "Raad van State"},
]


def test_keyed_differences_says_what_was_added_removed_and_changed() -> None:
    after = [
        {"code": "HR", "name": "Hoge Raad der Nederlanden"},
        {"code": "CRVB", "name": "Centrale Raad van Beroep"},
    ]
    assert keyed_differences(BEFORE, after, "code") == [
        "+ CRVB: Centrale Raad van Beroep",
        "- RVS: Raad van State",
        '~ HR: {"code": "HR", "name": "Hoge Raad"} -> '
        '{"code": "HR", "name": "Hoge Raad der Nederlanden"}',
    ]
    assert keyed_differences(BEFORE, BEFORE, "code") == []


@pytest.fixture
def data(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setattr(_data_file, "GraphStore", lambda: object())
    path = tmp_path / "courts.json"
    path.write_text(json.dumps({"courts": BEFORE}), encoding="utf-8")
    return path


def _command(data: Path, after: list[dict[str, Any]]):
    def rebuild(store: object, current: dict[str, Any]) -> dict[str, Any]:
        return {**current, "courts": after}

    return lambda argv: build_or_check(
        argv,
        doc="``lawgraph courts build|check``: the court table.",
        data=data,
        name="courts",
        rebuild=rebuild,
        differences=lambda a, b: keyed_differences(a["courts"], b["courts"], "code"),
    )


def test_a_check_with_a_difference_fails_and_writes_nothing(data: Path, capsys) -> None:
    command = _command(data, BEFORE[:1])
    result = command(["check"])
    assert result.errors == [f"1 changes against {data}: run `courts build`."]
    assert capsys.readouterr().out == "- RVS: Raad van State\n1 changes.\n"
    assert json.loads(data.read_text())["courts"] == BEFORE


def test_a_check_without_one_passes(data: Path, capsys) -> None:
    assert _command(data, BEFORE)(["check"]).errors == []
    assert capsys.readouterr().out == "0 changes.\n"


def test_a_build_writes_the_file(data: Path, tmp_path: Path, capsys) -> None:
    out = tmp_path / "out.json"
    result = _command(data, BEFORE[:1])(["build", "--output", str(out)])
    assert result.errors == []
    assert out.read_text(encoding="utf-8") == (
        json.dumps({"courts": BEFORE[:1]}, ensure_ascii=False, indent=1) + "\n"
    )
    assert capsys.readouterr().out.endswith(f"1 changes.\nWrote {out}.\n")


def test_the_help_is_the_first_line_of_the_docstring(data: Path, capsys) -> None:
    with pytest.raises(SystemExit):
        _command(data, BEFORE)(["--help"])
    assert "The court table." in capsys.readouterr().out
