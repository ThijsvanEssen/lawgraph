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
    assert not command.main(["set", "left-right", "nieuw", "--after", "sp"]).errors
    order = list(LISTS["left-right"].entries())
    assert order[order.index("sp") + 1] == "nieuw"
    assert not command.main(["set", "left-right", "nieuw", "--first"]).errors
    assert list(LISTS["left-right"].entries())[0] == "nieuw"
    assert not command.main(["remove", "left-right", "nieuw"]).errors
    assert "nieuw" not in LISTS["left-right"].entries()
    # an unordered list has no place
    assert command.main(
        ["set", "judgment-names", "ECLI:NL:HR:2020:1", "--first"]
    ).errors


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
    from lawgraph.core.parties import LEFT_TO_RIGHT, PARTY_ALIASES, party_color

    assert CURATED_NAMES["ECLI:NL:HR:1981:AG4158"] == ("Haviltex",)
    assert PARTY_ALIASES["GL-PvdA"] == "GroenLinks-PvdA"
    assert party_color("gl-pvda") == party_color("GroenLinks-PvdA") == "#46962B"
    assert party_color("cu") == party_color("ChristenUnie")
    assert party_color("KVP") is None
    assert LEFT_TO_RIGHT[0] == "sp"
    assert json.loads((curated.CURATED / "left_right.json").read_text())[
        "order"
    ] == list(LEFT_TO_RIGHT)
