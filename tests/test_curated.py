"""The lists kept by hand and ``lawgraph curated``, on a copy of ``data/curated/``."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from lawgraph.commands import curated as command
from lawgraph.core import curated
from lawgraph.core.curated import LISTS, place, problems


@pytest.fixture
def copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "curated"
    shutil.copytree(curated.CURATED, target)
    monkeypatch.setattr(curated, "CURATED", target)
    return target


def test_every_list_is_in_order_and_reads_back_as_it_is_written(copy: Path) -> None:
    assert problems() == []
    for name, curated_list in LISTS.items():
        before = curated_list.path.read_bytes()
        curated_list.store(curated_list.entries())
        assert curated_list.path.read_bytes() == before, name


def test_set_writes_a_valid_change_and_refuses_a_wrong_one(copy: Path) -> None:
    ok = command.main(
        [
            "set",
            "party-colors",
            "Nieuwe Partij",
            '{"color": "#123456", "aliases": ["NP"]}',
        ]
    )
    assert not ok.errors
    assert LISTS["party-colors"].entries()["Nieuwe Partij"]["color"] == "#123456"

    wrong = command.main(["set", "party-colors", "Andere", '{"color": "rood"}'])
    assert any("is no #rrggbb" in e for e in wrong.errors)
    assert "Andere" not in LISTS["party-colors"].entries()

    # an alias that is already another party's name
    taken = command.main(
        ["set", "party-colors", "X", '{"color": "#000000", "aliases": ["VVD"]}']
    )
    assert taken.errors


def test_an_ordered_list_takes_a_place(copy: Path) -> None:
    assert not command.main(
        ["set", "ministries", "nieuw", '{"name": "Nieuw"}', "--after", "az"]
    ).errors
    order = list(LISTS["ministries"].entries())
    assert order[order.index("az") + 1] == "nieuw"
    assert not command.main(
        ["set", "ministries", "nieuw", '{"name": "Nieuw"}', "--first"]
    ).errors
    assert list(LISTS["ministries"].entries())[0] == "nieuw"
    assert not command.main(["remove", "ministries", "nieuw"]).errors
    assert "nieuw" not in LISTS["ministries"].entries()
    # an unordered list has no place
    assert command.main(
        ["set", "judgment-names", "ECLI:NL:HR:2020:1", "--first"]
    ).errors


def test_the_seating_plan_is_kept_in_order_of_angle_and_names_its_plan(
    copy: Path,
) -> None:
    assert not command.main(
        ["set", "seating", "nsc", '{"abbreviation": "NSC", "angle": 90.0}']
    ).errors
    angles = [v["angle"] for v in LISTS["seating"].entries().values()]
    assert angles == sorted(angles)
    assert command.main(
        ["set", "seating", "x", '{"abbreviation": "X", "angle": 200}']
    ).errors
    source = LISTS["seating"].document()["source"]
    assert source["url"].startswith("https://www.tweedekamer.nl/")
    assert source["dated"] == "2026-06-01"


def test_a_judgment_name_needs_an_ecli_and_a_ministry_alias_a_ministry(
    copy: Path,
) -> None:
    assert command.main(
        ["set", "judgment-names", "ecli:nl:hr:2020:1", '{"names": ["X"], "note": null}']
    ).errors
    assert not command.main(
        [
            "set",
            "judgment-names",
            "ECLI:NL:HR:2020:1",
            '{"names": ["X"], "note": "test"}',
        ]
    ).errors
    assert command.main(
        ["set", "ministry-aliases", "Oorlogsministerie", '"nope"']
    ).errors
    assert not command.main(
        ["set", "ministry-aliases", "Oorlogsministerie", '"oorlog"']
    ).errors


def test_place() -> None:
    entries = {"a": 1, "b": 2}
    assert place(entries, "b", 3) == {"a": 1, "b": 3}
    assert place(entries, "c", 3) == {"a": 1, "b": 2, "c": 3}
    assert list(place(entries, "c", 3, after="a")) == ["a", "c", "b"]
    assert list(place(entries, "b", 2, after="")) == ["b", "a"]
    with pytest.raises(KeyError):
        place(entries, "c", 3, after="x")


def test_the_loaders_read_the_curated_lists() -> None:
    from lawgraph.core.judgment_names import CURATED_NAMES
    from lawgraph.core.parties import PARTY_ALIASES, SEATING, party_color

    assert CURATED_NAMES["ECLI:NL:HR:1981:AG4158"] == ("Haviltex",)
    assert PARTY_ALIASES["GL-PvdA"] == "GroenLinks-PvdA"
    assert party_color("gl-pvda") == party_color("GroenLinks-PvdA") == "#46962B"
    assert party_color("cu") == party_color("ChristenUnie")
    assert party_color("KVP") is None
    # the plan of June 2026, from the chair's left
    assert SEATING[:2] == ("sp", "pro") and SEATING[-2:] == ("fvd", "pvv")
    assert "nieuw_sociaal_contract" not in SEATING  # not seated in June 2026
    assert [
        f["key"]
        for f in json.loads((curated.CURATED / "seating.json").read_text())["factions"]
    ] == list(SEATING)
