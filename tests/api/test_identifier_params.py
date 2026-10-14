"""What each route takes as a dossier number, a dossier prefix or a BWB id: the pattern
its parameter has in the spec."""

from __future__ import annotations

import re

import pytest

from lawgraph.api.app import app

SPEC = app.openapi()


def _pattern(path: str, name: str) -> str:
    (operation,) = SPEC["paths"][path].values()
    (parameter,) = [p for p in operation["parameters"] if p["name"] == name]
    schema = parameter["schema"]
    for option in [schema, *schema.get("anyOf", [])]:
        if "pattern" in option:
            return str(option["pattern"])
    raise AssertionError(f"{path} {name}: no pattern")


FULL = [
    ("/api/dossiers/{number}", "number"),
    ("/api/dossiers/{number}/documents", "number"),
    ("/api/dossiers/{number}/timeline", "number"),
    ("/api/dossiers/{number}/changed-articles", "number"),
    ("/api/dossiers/{number}/mutations", "number"),
    ("/api/documents", "dossier"),
    ("/api/decisions", "dossier"),
]
PREFIX = [
    ("/api/dossiers", "number"),
    ("/api/feed", "dossier"),
    ("/api/feed/summary", "dossier"),
    ("/api/feed/periods", "dossier"),
    ("/api/feed.atom", "dossier"),
]
INSTRUMENT = [
    ("/api/feed", "instrument"),
    ("/api/feed/summary", "instrument"),
    ("/api/feed/periods", "instrument"),
    ("/api/feed.atom", "instrument"),
]


@pytest.mark.parametrize(("path", "name"), FULL + PREFIX)
@pytest.mark.parametrize("value", ["36600", "36600-VIII", "36956-(R2220)"])
def test_a_dossier_label_is_taken(path: str, name: str, value: str) -> None:
    assert re.fullmatch(_pattern(path, name), value)


@pytest.mark.parametrize(("path", "name"), FULL)
def test_a_full_number_needs_its_addition_after_the_dash(path: str, name: str) -> None:
    assert not re.fullmatch(_pattern(path, name), "37020-")


@pytest.mark.parametrize(("path", "name"), PREFIX)
def test_a_prefix_may_end_in_the_dash(path: str, name: str) -> None:
    assert re.fullmatch(_pattern(path, name), "37020-")


@pytest.mark.parametrize(("path", "name"), FULL + PREFIX)
@pytest.mark.parametrize("value", ["BWBR0005289", "36600 VIII", "-1"])
def test_what_is_no_dossier_is_refused(path: str, name: str, value: str) -> None:
    assert not re.fullmatch(_pattern(path, name), value)


@pytest.mark.parametrize(("path", "name"), INSTRUMENT)
@pytest.mark.parametrize("value", ["BWBR0052872", "bwbr0052872", "BWBV0001000"])
def test_a_bwb_id_is_taken_in_any_case(path: str, name: str, value: str) -> None:
    assert re.fullmatch(_pattern(path, name), value)


@pytest.mark.parametrize(("path", "name"), INSTRUMENT)
def test_what_is_no_bwb_id_is_refused(path: str, name: str) -> None:
    assert not re.fullmatch(_pattern(path, name), "32016R0679")
