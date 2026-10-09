"""The readable addresses, against the cases the front end is tested against too
(``tests/data/readable-paths.json``)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from lawgraph.core.readable_paths import Pad, pad_href, parse_path, path_of

CASES: dict[str, Any] = json.loads(
    (Path(__file__).parent / "data" / "readable-paths.json").read_text()
)


@pytest.mark.parametrize("case", CASES["paths"], ids=lambda c: c["path"])
def test_a_node_has_its_readable_path_and_the_path_reads_back(
    case: dict[str, Any],
) -> None:
    assert path_of(case["focus"], case["props"]) == case["path"]
    assert parse_path(case["path"]) is not None


@pytest.mark.parametrize("case", CASES["none"], ids=lambda c: c["focus"])
def test_a_node_without_a_readable_path(case: dict[str, Any]) -> None:
    assert path_of(case["focus"], case["props"]) is None


@pytest.mark.parametrize("case", CASES["parse"], ids=lambda c: c["path"])
def test_a_path_in_another_spelling_reads_as_its_canonical(
    case: dict[str, Any],
) -> None:
    pad = parse_path(case["path"])
    assert pad == Pad(**case["pad"])
    assert pad_href(pad) == case["canonical"]


@pytest.mark.parametrize("path", CASES["invalid"])
def test_any_other_path_is_no_readable_address(path: str) -> None:
    assert parse_path(path) is None
