"""The shell of the front end and the JSON files its build writes beside it: one that is
missing or does not read is a release that went wrong, logged with its path."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from lawgraph.api.seo import shell
from lawgraph.config import settings


@pytest.fixture
def index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    path = tmp_path / "index.html"
    path.write_text("<!doctype html><html><head></head><body></body></html>")
    (tmp_path / "spa-routes.json").write_text('[{"path": "/zoeken/"}]')
    (tmp_path / "start.json").write_text('{"heading": "Kop"}')
    monkeypatch.setattr(settings, "SPA_INDEX", str(path))
    shell.forget()
    yield path
    shell.forget()


def _errors(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]


def test_a_whole_build_is_read_without_a_word(
    index: Path, caplog: pytest.LogCaptureFixture
) -> None:
    read = shell.shell()
    assert set(read.routes) == {"/zoeken"} and read.start == {"heading": "Kop"}
    assert _errors(caplog) == []


@pytest.mark.parametrize(
    ("name", "text", "reason"),
    [
        ("spa-routes.json", None, "does not read: FileNotFoundError"),
        ("spa-routes.json", '[{"path": "/zoeken"', "does not read: JSONDecodeError"),
        ("spa-routes.json", '{"path": "/zoeken"}', "is no JSON list but a dict"),
        ("start.json", None, "does not read: FileNotFoundError"),
        ("start.json", "{", "does not read: JSONDecodeError"),
        ("start.json", "[]", "is no JSON dict but a list"),
    ],
)
def test_a_file_that_is_missing_or_does_not_read_is_logged_with_its_path(
    index: Path,
    caplog: pytest.LogCaptureFixture,
    name: str,
    text: str | None,
    reason: str,
) -> None:
    beside = index.parent / name
    if text is None:
        beside.unlink()
    else:
        beside.write_text(text)
    read = shell.shell()
    assert (read.routes if name == "spa-routes.json" else read.start) == {}
    (error,) = _errors(caplog)
    assert f"The front end's {beside} {reason}" in error
    shell.shell()  # kept until the shell changes: said once
    assert len(_errors(caplog)) == 1
