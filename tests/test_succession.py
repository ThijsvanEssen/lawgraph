"""Rows of a source checked against the articles of the old and the new law: what holds is a
pair of articles with its parts, the rest a gap, nothing corrected."""

from __future__ import annotations

from lawgraph.core.succession import (
    Gap,
    LawArticle,
    Place,
    SourceRow,
    place,
)

OLD = {
    "126ff": LawArticle("articles/bwbr0001903_126ff", "126ff"),
    "126ffa": LawArticle("articles/bwbr0001903_126ffa", "126ffa"),
    "126gg": LawArticle("articles/bwbr0001903_126gg", "126gg"),
    "126hh": LawArticle("articles/bwbr0001903_126hh", "126hh"),
    "126ii": LawArticle("articles/bwbr0001903_126ii", "126ii"),
    "127": LawArticle("articles/bwbr0001903_127", "127", repealed=True),
}
NEW = {
    "2.8.6": LawArticle("articles/stb_2026_56_2_8_6", "2.8.6", frozenset({"1", "2"})),
    "2.8.16": LawArticle("articles/stb_2026_56_2_8_16", "2.8.16", frozenset({"1"})),
}


def _row(old: str, part: str, text: str, article: str | None, *leden: str) -> SourceRow:
    return SourceRow(old, part, Place(text, article, leden), "p. 94")


def test_a_row_that_holds_is_a_part_of_its_pair() -> None:
    placed = place(
        [
            _row("126ffa", "1", "2.8.6, 1", "2.8.6", "1"),
            _row("126ffa", "2", "2.8.6, 1", "2.8.6", "1"),
            _row("126ffa", "2 a", "Besluit B2", None),
            _row("126ffa", "4", "2.8.6, 2", "2.8.6", "2"),
            _row("126ffa", "4", "2.8.6, 2", "2.8.6", "2"),  # once
        ],
        OLD,
        NEW,
    )
    assert placed.pairs == {
        ("articles/bwbr0001903_126ffa", "articles/stb_2026_56_2_8_6"): [
            {"from": "1", "to": "2.8.6, 1"},
            {"from": "2", "to": "2.8.6, 1"},
            {"from": "4", "to": "2.8.6, 2"},
        ]
    }


def test_a_row_that_does_not_hold_is_a_gap_and_no_pair() -> None:
    placed = place(
        [
            _row("126gg", "1", "2.9.1, 1", "2.9.1", "1"),
            _row("126ff", "4", "2.8.6, 3", "2.8.6", "3"),
            _row("126zz", "", "2.8.6", "2.8.6"),
            SourceRow("126ii", "2", Place("2.9.1.", None, (), readable=False), "p. 95"),
            _row("126hh", "1", "2.8.16, 1", "2.8.16", "1"),
        ],
        OLD,
        NEW,
    )
    assert list(placed.pairs) == [
        ("articles/bwbr0001903_126hh", "articles/stb_2026_56_2_8_16")
    ]
    assert placed.gaps[:4] == [
        Gap("no_new_article", "126gg", "1", "2.9.1, 1", "p. 94"),
        Gap("no_lid", "126ff", "4", "2.8.6, 3", "p. 94"),
        Gap("no_old_article", "126zz", "", "2.8.6", "p. 94"),
        Gap("unreadable", "126ii", "2", "2.9.1.", "p. 95"),
    ]


def test_an_old_article_without_a_place_is_a_gap_of_its_own() -> None:
    placed = place(
        [
            _row("126ff", "1", "vervallen (mvt)", None),
            _row("126ff", "2", "Besluit B2", None),
            _row("126ff", "3", "Besluit B2", None),
            _row("126gg", "1", "2.9.1, 1", "2.9.1", "1"),
            _row("126ffa", "1", "2.8.6, 1", "2.8.6", "1"),
        ],
        OLD,
        NEW,
    )
    # 127 is repealed: no gap
    assert [g for g in placed.gaps if g.kind != "no_new_article"] == [
        Gap("no_article", "126ff", text="vervallen (mvt); Besluit B2", where="p. 94"),
        Gap("not_placed", "126gg", where="p. 94"),
        Gap("no_row", "126hh"),
        Gap("no_row", "126ii"),
    ]
