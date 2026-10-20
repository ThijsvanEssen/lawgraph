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
            {"from": "1", "to": "2.8.6, 1", "article": "2.8.6", "leden": ["1"]},
            {"from": "2", "to": "2.8.6, 1", "article": "2.8.6", "leden": ["1"]},
            {"from": "4", "to": "2.8.6, 2", "article": "2.8.6", "leden": ["2"]},
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


def test_a_run_of_articles_is_each_article_of_it_in_the_order_of_the_law() -> None:
    old = {n: LawArticle(f"articles/wtw_{n}", n) for n in ("1.2", "1.3", "1.4", "2.1")}
    new = {
        n: LawArticle(f"articles/ow_{n}", n) for n in ("2.19", "2.20", "2.21", "2.21a")
    }
    placed = place(
        [
            SourceRow("1.2", "", Place("2.21", "2.21", ()), "rij 3", "kst", "1.4"),
            SourceRow(
                "2.1",
                "",
                Place("2.19 t/m 2.21a", "2.19", (), through="2.21a"),
                "rij 7",
                "kst",
            ),
            SourceRow(
                "2.1", "", Place("2.19 t/m 9.9", "2.19", (), through="9.9"), "rij 8"
            ),
        ],
        old,
        new,
    )
    assert list(placed.pairs) == [
        ("articles/wtw_1.2", "articles/ow_2.21"),
        ("articles/wtw_1.3", "articles/ow_2.21"),
        ("articles/wtw_1.4", "articles/ow_2.21"),
        ("articles/wtw_2.1", "articles/ow_2.19"),
        ("articles/wtw_2.1", "articles/ow_2.20"),
        ("articles/wtw_2.1", "articles/ow_2.21"),
        ("articles/wtw_2.1", "articles/ow_2.21a"),
    ]
    assert placed.pairs[("articles/wtw_1.3", "articles/ow_2.21")] == [
        {"from": "", "to": "2.21", "article": "2.21", "leden": []}
    ]
    # each article of a run is the article of its own pair, not the first of the run
    assert placed.pairs[("articles/wtw_2.1", "articles/ow_2.20")] == [
        {"from": "", "to": "2.19 t/m 2.21a", "article": "2.20", "leden": []}
    ]
    # a run whose end the law lacks is a gap of the row
    assert placed.gaps == [Gap("no_new_article", "2.1", "", "2.19 t/m 9.9", "rij 8")]


def test_a_run_of_old_articles_the_law_lacks_is_a_gap() -> None:
    placed = place(
        [SourceRow("126ff", "", Place("2.8.6", "2.8.6", ()), "rij 1", "kst", "126zz")],
        OLD,
        NEW,
    )
    assert placed.gaps[0] == Gap(
        "no_old_article", "126ff t/m 126zz", "", "2.8.6", "rij 1", "kst"
    )


def test_each_pair_names_the_sources_that_give_it() -> None:
    placed = place(
        [
            SourceRow("126ffa", "1", Place("2.8.6, 1", "2.8.6", ("1",)), "p. 4", "blg"),
            SourceRow(
                "126ffa", "2", Place("2.8.6, 2", "2.8.6", ("2",)), "rij 9", "kst"
            ),
            SourceRow("126ffa", "3", Place("2.8.6", "2.8.6", ()), "p. 5", "blg"),
        ],
        OLD,
        NEW,
    )
    assert placed.sources == {
        ("articles/bwbr0001903_126ffa", "articles/stb_2026_56_2_8_6"): ["blg", "kst"]
    }


def test_of_an_old_law_that_stays_an_article_without_a_row_is_no_gap() -> None:
    rows = [_row("126ff", "1", "vervallen (mvt)", None)]
    kinds = {g.kind for g in place(rows, OLD, NEW, replaced=False).gaps}
    assert "no_row" not in kinds
    assert "no_article" in kinds
    assert "no_row" in {g.kind for g in place(rows, OLD, NEW).gaps}


def test_a_number_is_read_as_the_law_writes_it() -> None:
    """The table of the new Sv writes "509ibis" (p. 127), the BWB "509i bis"."""
    old = {"509i bis": LawArticle("articles/bwbr0001903_509i_bis", "509i bis")}
    new = {
        "4.3.30": LawArticle("articles/stb_2026_56_4_3_30", "4.3.30", frozenset("5"))
    }
    placed = place([_row("509ibis", "", "4.3.30, 5", "4.3.30", "5")], old, new)
    assert list(placed.pairs) == [
        ("articles/bwbr0001903_509i_bis", "articles/stb_2026_56_4_3_30")
    ]
    assert placed.gaps == []
