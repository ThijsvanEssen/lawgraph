"""Rows of a source checked against the articles of the old and the new law: what holds is a
pair of articles with its parts, the rest a gap, nothing corrected."""

from __future__ import annotations

import pytest

from lawgraph.core.succession import (
    Gap,
    LawArticle,
    Place,
    SourceRow,
    Unplaced,
    divisions,
    outcome,
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
    # 127 is repealed: no gap; "vervallen (mvt)" is what the source answers, the rest is
    # kept as the source writes it
    assert [g for g in placed.gaps if g.kind != "no_new_article"] == [
        Gap("no_article", "126ff", text="Besluit B2", where="p. 94"),
        Gap("not_placed", "126gg", text="2.9.1, 1", where="p. 94"),
        Gap("no_row", "126hh"),
        Gap("no_row", "126ii"),
    ]
    # an old article that is a gap keeps its parts as the source writes them (``gat``)
    assert placed.unplaced["articles/bwbr0001903_126ff"] == Unplaced(
        [
            {"from": "1", "to": "vervallen (mvt)", "outcome": "vervallen"},
            {"from": "2", "to": "Besluit B2", "outcome": "gat"},
            {"from": "3", "to": "Besluit B2", "outcome": "gat"},
        ],
        [""],
        "gat",
    )


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
    rows = [_row("126ff", "1", "Besluit B2", None)]
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


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # blg-1081574 (p. 4, art. 2 and 10, with its typing error), kst-34986-3 (Waterwet,
        # Wet milieubeheer, Monumentenwet 1988), Richtlijn (EU) 2018/1972
        ("vervallen (mvt)", "vervallen"),
        ("vervalllen", "vervallen"),
        ("Vervallen.", "vervallen"),
        ("vervalt", "vervallen"),
        ("–", "niet_overgenomen"),
        ("—", "niet_overgenomen"),
        ("niet overgenomen", "niet_overgenomen"),
        ("keert niet terug", "niet_overgenomen"),
        ("Blijft in Waterwet", "blijft_in:Waterwet"),
        ("Blijft in Wm 10.6, tweede lid", "blijft_in:Wm"),
        # no answer: a place, or more than the answer
        ("Vervallen (zie 3.24)", None),
        ("Deels vervallen, deels in 2.18 eerste en tweede lid", None),
        ("Besluit B2", None),
        ("bijlage A", None),
    ],
)
def test_what_the_source_answers_instead_of_a_place(
    text: str, expected: str | None
) -> None:
    assert outcome(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("B6H3", [("boek 6", "hoofdstuk 3")]),
        ("algemeen B1H9", [("boek 1", "hoofdstuk 9")]),
        ("algemene regeling (B2T1.5)", [("boek 2", "titel 1.5")]),
        ("B6H4 Afdeling 4.1.3", [("boek 6", "hoofdstuk 4", "afdeling 4.1.3")]),
        ("Boek 8", [("boek 8",)]),
        ("afdeling 15.2", [("afdeling 15.2",)]),
        ("hoofdstuk 13 en 15", [("hoofdstuk 13",), ("hoofdstuk 15",)]),
        ("§ 1.2", [("paragraaf 1.2",)]),
        ("titel 10.5A", [("titel 10.5a",)]),
        ("Hfdst. IV", [("hoofdstuk iv",)]),
        ("Besluit B2", None),
        ("bijlage A", None),
        ("2.8.6, 1", None),
    ],
)
def test_the_divisions_a_place_names(
    text: str, expected: list[tuple[str, ...]] | None
) -> None:
    assert divisions(text) == expected


def test_what_the_source_answers_is_no_gap() -> None:
    """blg-1081574 p. 4: art. 10 lapses in each of its leden (one written "vervalllen");
    kst-34986-3: the Waterwet's 3.6a t/m 3.6e stay in the Waterwet."""
    old = {
        n: LawArticle(f"articles/wtw_{n}", n) for n in ("3.6a", "3.6b", "3.14", "10")
    }
    placed = place(
        [
            _row("10", "1", "vervalllen", None),
            _row("10", "2", "vervallen", None),
            SourceRow(
                "3.6a",
                "",
                Place("Blijft in Waterwet", None, ()),
                "rij 20",
                "kst",
                "3.6b",
            ),
            SourceRow("3.14", "", Place("–", None, ()), "rij 27", "kst"),
        ],
        old,
        NEW,
    )
    assert placed.gaps == []
    assert placed.pairs == {}
    assert {old: u.outcome for old, u in placed.unplaced.items()} == {
        "articles/wtw_10": "vervallen",
        "articles/wtw_3.6a": "blijft_in:Waterwet",
        "articles/wtw_3.6b": "blijft_in:Waterwet",
        "articles/wtw_3.14": "niet_overgenomen",
    }
    assert placed.unplaced["articles/wtw_10"].parts == [
        {"from": "1", "to": "vervalllen", "outcome": "vervallen"},
        {"from": "2", "to": "vervallen", "outcome": "vervallen"},
    ]


def test_an_outcome_of_a_part_of_an_article_placed_elsewhere() -> None:
    """blg-1081574 p. 4, art. 2: lid 1 in 1.2.9, lid 2 "vervallen (mvt)"."""
    old = {"2": LawArticle("articles/sv_2", "2")}
    new = {"1.2.9": LawArticle("articles/nsv_1_2_9", "1.2.9", frozenset({"1"}))}
    placed = place(
        [
            _row("2", "1", "1.2.9, 1", "1.2.9", "1"),
            _row("2", "2", "vervallen (mvt)", None),
            _row("2", "3", "Besluit B2", None),
        ],
        old,
        new,
    )
    assert list(placed.pairs) == [("articles/sv_2", "articles/nsv_1_2_9")]
    assert placed.gaps == []
    # of an article that is no gap only what the source answers
    assert placed.unplaced["articles/sv_2"] == Unplaced(
        [{"from": "2", "to": "vervallen (mvt)", "outcome": "vervallen"}],
        [""],
        "vervallen",
    )


def _in(number: str, *labels: str) -> LawArticle:
    return LawArticle(f"articles/wm_{number}", number, divisions=labels)


def test_a_division_of_the_old_law_is_each_article_of_it() -> None:
    """kst-34986-3, Wet milieubeheer: "§ 1.2 | 2.6, 2.18 … en § 16.3.5", "§ 2.4 | –"."""
    old = {
        "1.1a": _in("1.1a", "hoofdstuk 1"),
        "1.2": _in("1.2", "hoofdstuk 1", "paragraaf 1.2"),
        "1.3": _in("1.3", "hoofdstuk 1", "paragraaf 1.2"),
        "2.42": _in("2.42", "hoofdstuk 2", "paragraaf 2.4"),
    }
    new = {
        "2.6": LawArticle("articles/ow_2_6", "2.6"),
        "16.25": LawArticle(
            "articles/ow_16_25", "16.25", divisions=("hoofdstuk 16", "paragraaf 16.3.5")
        ),
    }
    placed = place(
        [
            SourceRow("§ 1.2", "", Place("2.6", "2.6", ()), "rij 3", "kst"),
            SourceRow("§ 1.2", "", Place("§ 16.3.5", None, ()), "rij 3", "kst"),
            SourceRow("§ 2.4", "", Place("–", None, ()), "rij 8", "kst"),
            SourceRow("§ 9.9", "", Place("2.6", "2.6", ()), "rij 9", "kst"),
        ],
        old,
        new,
        replaced=False,
    )
    assert placed.pairs == {
        ("articles/wm_1.2", "articles/ow_2_6"): [
            {"from": "", "to": "2.6", "article": "2.6", "leden": [], "via": "§ 1.2"}
        ],
        ("articles/wm_1.3", "articles/ow_2_6"): [
            {"from": "", "to": "2.6", "article": "2.6", "leden": [], "via": "§ 1.2"}
        ],
    }
    assert placed.unplaced["articles/wm_2.42"].parts == [
        {"from": "", "to": "–", "outcome": "niet_overgenomen", "via": "§ 2.4"}
    ]
    # a division the old law does not have
    assert placed.gaps == [Gap("no_old_article", "§ 9.9", "", "2.6", "rij 9", "kst")]


def test_a_division_of_the_new_law_places_nothing() -> None:
    """blg-1081574: "algemeen B1H9" (a division the new Sv has), "B6H3" (one it does not
    have: Boek 6 has no Hoofdstuk 3 in Stb. 2026, 56). The graph has no node of a
    division."""
    old = {n: LawArticle(f"articles/sv_{n}", n) for n in ("12", "539a")}
    new = {
        "1.9.1": LawArticle(
            "articles/nsv_1_9_1", "1.9.1", divisions=("boek 1", "hoofdstuk 9")
        )
    }
    placed = place(
        [_row("12", "4", "algemeen B1H9", None), _row("539a", "", "B6H3", None)],
        old,
        new,
    )
    assert placed.pairs == {}
    assert placed.gaps == [
        Gap("in_division", "12", text="algemeen B1H9", where="p. 94"),
        Gap("no_division", "539a", text="B6H3", where="p. 94"),
    ]
    assert placed.unplaced["articles/sv_539a"] == Unplaced(
        [{"from": "", "to": "B6H3", "outcome": "gat"}], [""], "gat"
    )


def test_a_place_in_another_law() -> None:
    """kst-34986-3, Wro 3.30: "5.45, 16.7 en afdeling 3.5 Awb"; kst-34878-3, WEC 47b:
    "12 en 47b WEC" (12 of the new law, 47b stays in the WEC)."""
    old = {n: LawArticle(f"articles/wro_{n}", n) for n in ("3.30", "47b")}
    new = {"5.45": LawArticle("articles/ow_5_45", "5.45")}
    awb = {"3:11": LawArticle("articles/awb_3_11", "3:11")}
    placed = place(
        [
            _row("3.30", "", "5.45", "5.45"),
            SourceRow("3.30", "", Place("3:11 Awb", "3:11", (), law="Awb"), "rij 1"),
            SourceRow("3.30", "", Place("1 Sr", "1", (), law="Sr"), "rij 1"),
            SourceRow("47b", "", Place("47b WEC", "47b", (), law="WEC"), "rij 2"),
        ],
        old,
        new,
        replaced=False,
        laws={"Awb": awb, "Sr": None, "WEC": old},
    )
    assert list(placed.pairs) == [
        ("articles/wro_3.30", "articles/ow_5_45"),
        ("articles/wro_3.30", "articles/awb_3_11"),
    ]
    assert placed.gaps == [Gap("no_law", "3.30", "", "1 Sr", "rij 1")]
    assert placed.unplaced["articles/wro_47b"].outcome == "blijft_in:WEC"
