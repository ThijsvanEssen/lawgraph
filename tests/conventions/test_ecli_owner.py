"""An ECLI is read in ``core/ecli.py`` only: its patterns, its parts and its key."""

from __future__ import annotations

import pathlib
import re

import pytest

from tests.conventions._scan import SRC, _python_files

ECLI_HOME = SRC / "core" / "ecli.py"
# A pattern for an ECLI or its key ("ECLI:[A-Z]{2}", "(?:ECLI:NL:)?(?P<court>",
# "ecli_[a-z]{2}"), or an ECLI split to take a part of it.
_ECLI_PATTERN = re.compile(
    r"""ecli[:_][^\s'"`]{0,12}?(?:\[[A-Za-z0-9]|\\d|\(\?)""", re.IGNORECASE
)
_ECLI_SPLIT = re.compile(r"""ecli[\w.()]*\.split\(["']:["']\)""", re.IGNORECASE)


def _ecli_readers(source: str) -> list[str]:
    return [
        match.group(0)
        for pattern in (_ECLI_PATTERN, _ECLI_SPLIT)
        for match in pattern.finditer(source)
    ]


def test_the_ecli_scan_would_catch_a_pattern() -> None:
    assert _ecli_readers(r're.compile(r"^ECLI:[A-Z]{2}:[A-Z0-9.]{1,7}:\d{4}$")')
    assert _ecli_readers(r'r"\b(?:ECLI:NL:)?(?P<court>[A-Z]{2,8}):(?P<year>\d{4})"')
    assert _ecli_readers(r"WHERE ecli ~ '^ECLI:NL:[A-Z]+:[0-9]{4}'")
    assert _ecli_readers(r're.compile(r"^ecli_[a-z]{2}_[a-z0-9]+$")')
    assert _ecli_readers('parts = ecli.strip().upper().split(":")')
    assert not _ecli_readers('"ECLI:NL:HR:2019:2006" and ecli_of_key(key)')
    assert not _ecli_readers("the ECLI: ``ECLI:NL:HR:2019:1858``")


@pytest.mark.parametrize("path", _python_files(), ids=lambda p: p.name)
def test_an_ecli_is_only_read_in_core_ecli(path: pathlib.Path) -> None:
    if path == ECLI_HOME:
        return
    found = _ecli_readers(path.read_text())
    assert not found, (
        f"{path.relative_to(SRC)} reads an ECLI itself ({found}); use core/ecli.py."
    )
