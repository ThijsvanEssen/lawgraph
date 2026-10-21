"""The transposition tables in the XML of a Kamerstuk: excerpts of the second table of the new
Wetboek van Strafvordering (kst-36636-3, "Huidig naar nieuw"), of the Omgevingswet's table of
the Waterwet (kst-34986-3, Bijlage 2), of the Wet voortgezet onderwijs 2020 (kst-35297-3), of
the Invoeringsbesluit Omgevingswet (Stb. 2020, 400), of the tables of a proposed law (the
Energiewet, the Wet dieren, the Mediawet 2008, the Waarborgwet 2019, the Wet op de Nederlandse
identiteitskaart, the Erfgoedwet and the Wet natuurbescherming), and the layouts a table
holds."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET

import pytest

from lawgraph.core.succession import Place, SourceRow
from lawgraph.core.transposition_xml import (
    Reference,
    XmlTable,
    cell_parts,
    places,
    proposed_name,
    read_tables,
    references,
)
from lawgraph.db.queries.successions import folded, name_pattern
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


def test_the_tables_of_the_sv_and_the_ow_read_as_they_did() -> None:
    """The excerpts of kst-36636-3 and kst-34986-3 give the rows they gave before a table of
    a proposed law was read (``transposition_xml_rows_sv_ow.json``)."""
    expected = json.loads((FIXTURES / "transposition_xml_rows_sv_ow.json").read_text())
    for source, tables in expected.items():
        xml = (FIXTURES / f"{source.replace('-', '_')}_excerpt.xml").read_text()
        assert [
            {
                "table": t.name,
                "columns": list(t.columns) if t.columns else None,
                "title_law": t.title_law,
                "problem": t.problem,
                "rows": [
                    [
                        r.old_article,
                        r.part,
                        r.place.text,
                        r.place.article,
                        list(r.place.leden),
                        r.place.readable,
                        r.place.through,
                        r.where,
                        r.old_through,
                    ]
                    for r in t.rows()
                ],
            }
            for t in read_tables(xml, source)
        ] == tables


def _read(fixture: str) -> list[XmlTable]:
    source = fixture.replace("_", "-")
    return read_tables((FIXTURES / f"{fixture}_excerpt.xml").read_text(), source)


def _rows(table: XmlTable) -> list[tuple[str, str, str, str | None]]:
    return [
        (r.old_article, r.part, r.place.text, r.place.article) for r in table.rows()
    ]


def test_a_column_of_the_proposed_law_beside_one_of_the_old_law() -> None:
    """The Energiewet (kst-36378-3): ``Elektriciteitswet 1998 | Onderwerp | Wetsvoorstel
    Energiewet | Opmerking``. Its tables of EU acts name no law in a column of their own."""
    eu, table = _read("kst_36378_3")
    assert eu.problem == "no column of an old and of a new law"
    assert (table.columns, table.proposed) == (
        ("Elektriciteitswet 1998", "Wetsvoorstel Energiewet"),
        ("Energiewet",),
    )
    assert _rows(table)[:4] == [
        ("1", "eerste lid, onderdeel a", "1.1", "1.1"),
        ("1", "eerste lid, onderdeel b", "Onze Minister", None),
        ("1", "tweede lid", "1.3, derde lid", "1.3"),
        ("1", "derde lid", "1.3, eerste lid", "1.3"),
    ]
    assert _rows(table)[-4:] == [
        ("2", "", "Vervallen", None),  # "2 t/m 4": the run of the old law
        ("4a", "eerste lid", "5.13, eerste lid en vierde lid onderdeel a", "5.13"),
        ("7", "", "5.25", "5.25"),
        ("7a", "", "Vervallen", None),
    ]
    assert table.rows()[-4].old_through == "4"
    assert table.rows()[-3].place.leden == ("1", "4")


def test_a_table_under_no_heading_that_names_it() -> None:
    """The Wet dieren (kst-31389-3, an older paper: no ``colname``, ``<tuskop>``): a table
    per old law, ``<old law> | Wetsvoorstel | Bijzonderheden``, the law of the proposal named
    by the dossier (``… (Wet dieren)``). Only the first has a heading that names it; the
    one of the EU's directives names no law."""
    first, second = _read("kst_31389_3")
    assert (first.columns, first.proposed) == (
        ("Diergeneesmiddelenwet", "Wetsvoorstel"),
        ("Wet dieren",),
    )
    assert (second.name, second.columns) == (
        "Kaderwet diervoeders | Wetsvoorstel",
        ("Kaderwet diervoeders", "Wetsvoorstel"),
    )
    assert _rows(second)[4:] == [
        (
            "2",
            "tweede tot en met vierde lid",
            "art. 2.18, tweede lid, onderdelen a en b",
            "2.18",
        ),
        ("3", "", "art. 2.18, tweede lid, onderdeel a", "2.18"),
        ("3", "", "art. 2.2, zevende lid, onderdeel e", "2.2"),
    ]


def test_a_proposed_law_whose_year_is_still_open() -> None:
    """The Mediawet 2008 (kst-31356-3): ``Huidige Mediawet | Mediawet 20..``."""
    (table,) = _read("kst_31356_3")
    assert (table.columns, table.proposed) == (
        ("Mediawet", "Mediawet 20.."),
        ("Mediawet 20..",),
    )
    assert _rows(table)[3:] == [
        ("9", "", "art. 7.1, lid 1 en 2", "7.1"),
        ("10", "", "art. 7.2", "7.2"),
        ("10", "", "7.3", "7.3"),
        ("11", "", "art. 7.4", "7.4"),
        ("11", "", "7.8, lid 1", "7.8"),
        ("12", "", "art. 7.5 t/m 7.7", "7.5"),
    ]
    assert table.rows()[3].place.leden == ("1", "2")


def test_pairs_of_columns_side_by_side_either_way() -> None:
    """The Waarborgwet 2019 (kst-35075-3): ``A`` new to old, ``B`` old to new, under one
    head; the Wet op de Nederlandse identiteitskaart (kst-36644-3): ``Wetsvoorstel |
    Paspoortwet`` twice."""
    a, b = _read("kst_35075_3")
    assert (a.name, a.columns, a.proposed) == (
        "Artikel wetsvoorstel Waarborgwet | Artikel Waarborgwet 1986",
        ("Waarborgwet 1986", "Artikel wetsvoorstel Waarborgwet"),
        ("Waarborgwet", "Waarborgwet 20.."),
    )
    # "7, lid 5, 22, 26 en 30, lid 4": a lid, then the next article
    assert _rows(a)[:4] == [
        ("7", "lid 5", "1", "1"),
        ("22", "", "1", "1"),
        ("26", "", "1", "1"),
        ("30", "lid 4", "1", "1"),
    ]
    assert b.name == "Artikel Waarborgwet 1986 | Artikel wetsvoorstel Waarborgwet"
    assert _rows(b) == [("1", "", "7", "7"), ("2", "", "14", "14"), ("3", "", "7", "7")]

    first, second = _read("kst_36644_3")
    assert (first.columns, first.proposed) == (
        ("Paspoortwet", "Wetsvoorstel"),
        ("Wet op de Nederlandse identiteitskaart",),
    )
    assert _rows(second) == [
        ("33", "", "21", "21"),
        ("34", "", "22", "22"),
        ("36", "", "23", "23"),
    ]


def test_the_old_law_in_the_title_over_old_and_new() -> None:
    """The Erfgoedwet (kst-34109-3): ``oud | nieuw | opmerking`` under the old law's name, a
    cell of the new law in parts."""
    unesco, cultuurbezit = _read("kst_34109_3")
    assert (unesco.columns, unesco.title_law, unesco.proposed) == (
        ("oud", "nieuw"),
        "Uitvoeringswet UNESCO-verdrag 1970",
        ("Erfgoedwet",),
    )
    assert _rows(unesco)[:2] == [
        ("1", "Onder a", "1.1", "1.1"),
        ("1", "Onder b-d", "6.1", "6.1"),
    ]
    assert _rows(unesco)[-1] == ("6", "", "vervalt", None)
    assert _rows(cultuurbezit)[2:4] == [
        ("2", "Eerste lid", "3.7, eerste lid", "3.7"),
        ("2", "Tweede en derde lid", "3.7, vierde lid", "3.7"),
    ]


def test_a_place_of_the_old_law_and_its_leden_below_it() -> None:
    """The Wet natuurbescherming (kst-33348-3, Tabel 3. Boswet): ``Onderwerp | Plaats |
    Plaats wetsvoorstel``, ``Afd. I`` and ``Artikel 1`` without a place, ``Lid 1`` below it."""
    (table,) = _read("kst_33348_3")
    assert (table.columns, table.title_law, table.proposed) == (
        ("Plaats", "Plaats wetsvoorstel"),
        "Boswet",
        ("Wet natuurbescherming",),
    )
    assert _rows(table)[3:5] == [
        ("1", "Lid 2", "1.1, lid 1 en 2", "1.1"),
        ("1", "Lid 3", "4.1", "4.1"),
    ]
    assert table.rows()[3].place.leden == ("1", "2")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Eerste lid: 1.1 Tweede lid: 8.5",
            [("Eerste lid", "1.1"), ("Tweede lid", "8.5")],
        ),
        ("Onder a: 1.1 Onder b-d: 6.1", [("Onder a", "1.1"), ("Onder b-d", "6.1")]),
        (
            "Eerste tot en met derde lid: 14 Vierde lid: 25",
            [("Eerste tot en met derde lid", "14"), ("Vierde lid", "25")],
        ),
        ("Achtste lid: vervalt", [("Achtste lid", "vervalt")]),
        ("3.7, eerste lid", None),
        ("Zie: 3.1", None),
    ],
)
def test_a_cell_in_parts(text: str, expected: list[tuple[str, str]] | None) -> None:
    assert cell_parts(text) == expected


@pytest.mark.parametrize(
    ("head", "name"),
    [
        ("Wetsvoorstel", None),
        ("Plaats wetsvoorstel", None),
        ("nieuw", None),
        ("Wetsvoorstel Energiewet", "Energiewet"),
        ("Artikel wetsvoorstel Waarborgwet", "Waarborgwet"),
        ("Mediawet (20..)", "Mediawet (20..)"),
        ("Wetsvoorstel (tenzij anders bepaald)", None),
        (
            "Te implementeren in wetsvoorstel Aanbestedingswet 20.., tenzij anders is "
            "aangegeven",
            "Aanbestedingswet 20..",
        ),
    ],
)
def test_the_name_a_column_of_a_proposed_law_gives(head: str, name: str | None) -> None:
    assert proposed_name(head) == name


def test_a_cell_of_the_old_law_with_no_letter_or_figure_is_no_row() -> None:
    """``Wetsvoorstel | Paspoortwet``: ``–``, an article of the proposed law that has none
    of the old one."""
    (table,) = read_tables(
        _xml(_row("a", "–", "5") + _row("b", "3", "6")).replace(
            "Artikel Wet y", "Wetsvoorstel"
        ),
        "kst-1-3",
    )
    assert _rows(table) == [("3", "", "6", "6")]


@pytest.mark.parametrize(
    ("name", "titles"),
    [
        ("Mediawet 20..", {"Mediawet 2008": True, "Mediawet": False}),
        ("WVO 20xx", {"WVO 2020": True, "WVO": False}),
        ("Omgevings-wet", {"Omgevingswet": True, "Omgevingswet 2020": False}),
    ],
)
def test_a_name_of_a_law_and_the_titles_it_matches(
    name: str, titles: dict[str, bool]
) -> None:
    pattern = name_pattern(name)
    assert {t: bool(re.fullmatch(pattern, folded(t))) for t in titles} == titles
