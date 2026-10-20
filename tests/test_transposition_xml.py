"""The transposition tables in the XML of a Kamerstuk: excerpts of the second table of the new
Wetboek van Strafvordering (kst-36636-3, "Huidig naar nieuw"), of the Omgevingswet's table of
the Waterwet (kst-34986-3, Bijlage 2), of the Wet voortgezet onderwijs 2020 (kst-35297-3) and
of the Invoeringsbesluit Omgevingswet (Stb. 2020, 400), and the layouts a table holds."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from lawgraph.core.succession import Place, SourceRow
from lawgraph.core.transposition_xml import (
    Reference,
    XmlTable,
    places,
    read_tables,
    references,
)
from lawgraph.pipelines.semantic._transposition_tables import (
    Table,
    _xml_tables,
    in_law_order,
    new_column,
)
from tests.fakes import InMemoryStore
from tests.paths import FIXTURES


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "8.2.26, vierde lid",
            [Reference("8.2.26, vierde lid", "8.2.26", "vierde lid", ("4",))],
        ),
        (
            "1.1, eerste en tweede lid",
            [
                Reference(
                    "1.1, eerste en tweede lid",
                    "1.1",
                    "eerste en tweede lid",
                    ("1", "2"),
                )
            ],
        ),
        ("2.1 en 2.2", [Reference("2.1", "2.1"), Reference("2.2", "2.2")]),
        ("8.1.3 8.1.4", [Reference("8.1.3", "8.1.3"), Reference("8.1.4", "8.1.4")]),
        ("5.8 t/m 5.14", [Reference("5.8 t/m 5.14", "5.8", through="5.14")]),
        ("1.2–1.4", [Reference("1.2–1.4", "1.2", through="1.4")]),
        (
            "6:6:36, eerste lid, eerste tot en met derde zin",
            [
                Reference(
                    "6:6:36, eerste lid, eerste tot en met derde zin",
                    "6:6:36",
                    "eerste lid, eerste tot en met derde zin",
                    ("1",),
                )
            ],
        ),
        (
            "6, derde en zesde lid, en 7",
            [
                Reference(
                    "6, derde en zesde lid", "6", "derde en zesde lid", ("3", "6")
                ),
                Reference("7", "7"),
            ],
        ),
        (
            "2.31, eerste lid, onder a",
            [
                Reference(
                    "2.31, eerste lid, onder a", "2.31", "eerste lid, onder a", ("1",)
                )
            ],
        ),
        ("artikel 1.1a", [Reference("artikel 1.1a", "1.1a")]),
        ("5.33 jo. 16.15 en 16.16", None),
        ("§ 2.3", None),
        ("", None),
    ],
)
def test_the_references_of_a_cell(text: str, expected: list[Reference] | None) -> None:
    assert references(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("–", [Place("–", None, ())]),
        ("niet overgenomen", [Place("niet overgenomen", None, ())]),
        (
            "afdelingen 16.3, 16.8 en 23.1",
            [Place("afdelingen 16.3, 16.8 en 23.1", None, ())],
        ),
        (
            "4.3, 5.1 en bijlage A",
            [
                Place("4.3", "4.3", ()),
                Place("5.1", "5.1", ()),
                Place("bijlage A", None, ()),
            ],
        ),
        (
            "Komt terug in 13.1 en 13.3 Omgevingswet.",
            [
                Place(
                    "Komt terug in 13.1 en 13.3 Omgevingswet.", None, (), readable=False
                )
            ],
        ),
        (
            "2.19 t/m 2.21a",
            [Place("2.19 t/m 2.21a", "2.19", (), through="2.21a")],
        ),
        ("", []),
    ],
)
def test_the_places_a_cell_of_the_new_law_gives(
    text: str, expected: list[Place]
) -> None:
    assert places(text) == expected


def test_the_half_huidig_naar_nieuw_of_one_law() -> None:
    xml = (FIXTURES / "kst_36636_3_excerpt.xml").read_text()
    (table,) = read_tables(
        xml, "kst-36636-3"
    )  # the half "Nieuw naar huidig" is not read
    assert (table.name, table.columns, table.title_law, table.problem) == (
        "III. TRANSPONERINGSTABELLEN – Huidig naar nieuw",
        None,
        None,
        None,
    )
    assert [(r.old_article, r.part, r.place.text, r.where) for r in table.rows()] == [
        ("5.1.1", "eerste lid", "8.2.1", "rij 2"),
        ("6:1:1", "eerste lid", "1.10.1", "rij 6"),
        ("6:1:1", "tweede lid", "7.1.1, eerste lid", "rij 7"),
        ("6:1:1", "derde lid", "7.1.1, tweede lid", "rij 8"),
        ("6:1:2", "", "1.10.2, eerste lid", "rij 9"),
        ("6:1:5", "derde lid", "niet overgenomen", "rij 10"),
    ]
    assert table.rows()[2].source == "kst-36636-3"


def test_a_table_with_a_column_per_law() -> None:
    xml = (FIXTURES / "kst_34986_3_excerpt.xml").read_text()
    table, _woningwet = read_tables(xml, "kst-34986-3")
    assert (table.name, table.columns, table.title_law) == (
        "h. Transponeringstabel Waterwet",
        ("Wtw", "Omgevingswet"),
        "Waterwet",
    )
    assert table.rows()[1] == SourceRow(
        "1.2", "", Place("1.5", "1.5", ()), "rij 3", "kst-34986-3", "1.4"
    )
    assert [(r.old_article, r.place.text) for r in table.rows()[3:5]] == [
        ("2.1", "1.3"),
        ("2.1", "4.23"),
    ]


def _xml(body: str, *, title: str = "a. Transponeringstabel Wet x") -> str:
    head = (
        "<thead><row><entry colname='col1'><al>Onderwerp</al></entry>"
        "<entry colname='col2'><al>Artikel</al><al>Wet x</al></entry>"
        "<entry colname='col3'><al>Artikel Wet y</al></entry></row></thead>"
    )
    return (
        "<officiele-publicatie><kamerstuk><bijlage><kop><titel>BIJLAGE</titel></kop>"
        f"<table><title>{title}</title><tgroup>{head}<tbody>{body}</tbody></tgroup>"
        "</table></bijlage></kamerstuk></officiele-publicatie>"
    )


def _row(*cells: str, more: dict[str, int] | None = None) -> str:
    entries = "".join(
        f"<entry colname='col{i}' morerows='{(more or {}).get(f'col{i}', 0)}'>"
        f"<al>{cell}</al></entry>"
        for i, cell in enumerate(cells, start=1)
        if cell
    )
    return f"<row>{entries}</row>"


def test_a_row_that_names_only_a_part_continues_the_one_above() -> None:
    body = (
        "<row><entry namest='col1' nameend='col3'><al>Hoofdstuk 2</al></entry></row>"
        + _row("Intrekken", "2.33, tweede lid", "5.40, tweede lid")
        + _row("", "onder a", "onder b")
        + _row("", "onder c", "–")
        + _row("", "onder d", "onder a")
        + _row("Op verzoek", "2.33, derde lid", "onder a")
    )
    (table,) = read_tables(_xml(body), "kst-1-3")
    assert [
        (r.old_article, r.part, r.place.text, r.place.article) for r in table.rows()
    ] == [
        ("2.33", "tweede lid", "5.40, tweede lid", "5.40"),
        ("2.33", "tweede lid, onder a", "5.40, tweede lid, onder b", "5.40"),
        ("2.33", "tweede lid, onder c", "–", None),
        ("2.33", "tweede lid, onder d", "5.40, tweede lid, onder a", "5.40"),
        # a row of its own that names only a part of the new law does not read
        ("2.33", "derde lid", "onder a", None),
    ]
    assert table.rows()[1].place.leden == ("2",)
    assert not table.rows()[-1].place.readable


def test_a_cell_over_more_rows_holds_for_each() -> None:
    body = _row("Toetsing", "2.12, eerste lid", "5.21", more={"col3": 1}) + _row(
        "Onderbouwing", "2.12, tweede lid"
    )
    (table,) = read_tables(_xml(body), "kst-1-3")
    assert [(r.part, r.place.text) for r in table.rows()] == [
        ("eerste lid", "5.21"),
        ("tweede lid", "5.21"),
    ]


def test_a_row_of_the_old_law_that_is_no_reference_stays_a_row() -> None:
    (table,) = read_tables(_xml(_row("Toetsing", "§ 2.3", "§ 5.1.3")), "kst-1-3")
    assert table.rows() == (
        SourceRow("§ 2.3", "", Place("§ 5.1.3", None, ()), "rij 1", "kst-1-3"),
    )


def test_what_is_no_transposition_table() -> None:
    no_columns = _xml(_row("a", "b", "c")).replace("Artikel", "Bepaling")
    assert read_tables(no_columns, "kst-1-3") == [
        XmlTable(
            "a. Transponeringstabel Wet x",
            "kst-1-3",
            problem="no column of an old and of a new law",
        )
    ]
    assert read_tables(_xml(_row("a", "1", "2"), title="Overzicht"), "kst-1-3") == []
    with pytest.raises(ET.ParseError):  # kapot is not "no tables"
        read_tables("<not-closed>", "kst-1-3")


def test_a_table_reads_the_other_way_when_its_second_column_is_the_old_law() -> None:
    body = _row("Toetsing", "5.21", "2.12, eerste lid") + _row("", "5.40", "2.33")
    (table,) = read_tables(_xml(body), "kst-1-3")
    assert table.columns == ("Wet x", "Wet y")
    assert [
        (r.old_article, r.part, r.place.text) for r in table.rows(reverse=True)
    ] == [
        ("2.12", "eerste lid", "5.21"),
        ("2.33", "", "5.40"),
    ]


@pytest.mark.parametrize(
    ("laws", "dossier", "titled", "expected"),
    [
        # the dossier enacted the second: the columns run old to new
        (("old", "new"), {"new"}, None, 1),
        # the dossier enacted the first: the table runs the other way
        (("new", "old"), {"new"}, None, 0),
        # the dossier enacted neither (the Invoeringswet Omgevingswet): the title names the old
        (("wtw", "ow"), set(), "wtw", 1),
        (("ow", "wtw"), {"invoeringswet"}, "wtw", 0),
        # nothing tells
        (("a", "b"), set(), None, None),
        (("a", "b"), {"a", "b"}, None, None),
    ],
)
def test_which_column_is_the_new_law(
    laws: tuple[str, str], dossier: set[str], titled: str | None, expected: int | None
) -> None:
    assert new_column(laws, dossier, titled) == expected


def test_a_memorandum_whose_xml_does_not_read_is_a_table_that_says_so() -> None:
    """Not "no tables": ``semantic tk-transposition-tables`` notes it with its source."""
    record = {"external_id": "kst-34986-3", "payload_text": "<kamerstuk><tabel>"}
    assert list(_xml_tables(InMemoryStore(), record)) == [
        Table("kst-34986-3", "34986", problem="the XML does not read")
    ]


@pytest.mark.parametrize(
    ("fixture", "source", "problem"),
    [
        # a column per law, each with a column of its leden: two old laws are no pair
        (
            "kst_35297_3_excerpt.xml",
            "kst-35297-3",
            "columns not recognised: 3 of articles "
            "(artikel WVO | artikel WVO-BES | artikel WVO 20xx)",
        ),
        # the old regulation's article and its places in the Omgevingswet and an AMvB
        (
            "stb_2020_400_excerpt.xml",
            "stb-2020-400",
            "columns not recognised: 3 of articles "
            "(Artikel | Artikel Omgevingswet | Artikel AMvB)",
        ),
    ],
)
def test_a_head_with_more_than_two_columns_of_articles_is_not_read(
    fixture: str, source: str, problem: str
) -> None:
    (table,) = read_tables((FIXTURES / fixture).read_text(), source)
    assert (table.columns, table.cells, table.problem) == (None, (), problem)


def test_a_historical_identity_stands_where_its_number_does() -> None:
    """The Wro has lost 8.4a to 8.4f (into the Omgevingswet); its table (kst-34986-3, rij
    118) names them as a run."""

    def article(number: str, historical: bool) -> dict[str, object]:
        return {"number": number, "historical": historical}

    rows = [
        article("8.4", False),
        article("8.5", False),
        article("9.1", False),
        article("8.4b", True),
        article("8.4a", True),
        article("9.4", True),
    ]
    assert [row["number"] for row in in_law_order(rows)] == [
        "8.4",
        "8.4a",
        "8.4b",
        "8.5",
        "9.1",
        "9.4",
    ]
