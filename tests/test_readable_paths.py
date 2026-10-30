"""The readable addresses, against the cases the front end is tested against too
(``tests/data/readable-paths.json``)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from lawgraph.core.models import judgment_id, make_node_key
from lawgraph.core.publications import law_key
from lawgraph.core.readable_paths import (
    STB_LAW,
    Pad,
    pad_href,
    parse_path,
    path_of,
    short_law_path,
)

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


# The key a node is written under, of the addresses that name it without a lookup (the
# ``focus`` section the front end opens an address by): as its normalizer keys it.
_KEY_OF: dict[str, Any] = {
    "uitspraak": judgment_id,
    "wet": lambda a: (
        f"instruments/{law_key(a.lower()) if STB_LAW.match(a) else a.lower()}"
    ),
    "dossier": lambda a: f"dossiers/{make_node_key(a)}",
    "kabinet": lambda a: f"cabinets/{a}",
    "ministerie": lambda a: f"ministries/{a}",
    "fractie": lambda a: f"factions/{a}",
}


@pytest.mark.parametrize("case", CASES["focus"], ids=lambda c: c["path"])
def test_an_address_names_the_key_its_node_is_stored_under(
    case: dict[str, Any],
) -> None:
    pad = parse_path(case["path"])
    assert pad is not None
    key_of = _KEY_OF.get(pad.soort)
    assert (key_of(pad.a) if key_of else None) == case["focus"]


@pytest.mark.parametrize(
    ("path", "pad"),
    [
        ("/awb", Pad("wet", "awb")),
        ("/awb/8:75", Pad("artikel", "awb", "8:75")),
        ("/Sr/287", Pad("artikel", "Sr", "287")),
        ("/vw%202000/1", Pad("artikel", "vw 2000", "1")),
        ("/bw/7", Pad("boek", "bw", "7")),
        ("/BW/7A", Pad("boek", "BW", "7A")),
        ("/bw/7/658", Pad("artikel", "bw", "7:658")),
        ("/bw/6:162", Pad("artikel", "bw", "6:162")),
    ],
)
def test_a_law_at_its_short_address(path: str, pad: Pad) -> None:
    assert short_law_path(path) == pad


@pytest.mark.parametrize(
    "path",
    ["/", "/bw", "/awb/8/75", "/bw/7/658/1", "/wetten/awb", "/kamerstukken/36496",
     "/stb/2026", "/leden/x", "/1bw/1", "/%ff", "/awb/%20"],
)  # fmt: skip
def test_no_short_address(path: str) -> None:
    assert short_law_path(path) is None
