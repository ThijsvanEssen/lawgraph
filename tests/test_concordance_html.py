"""The concordance table of an EU act read from its CELLAR HTML (excerpts of the real pages):
a codification (Verordening (EU) 2017/1001), a recast (Verordening (EU) 2019/943), a recast
of four directives with a column each (Richtlijn (EU) 2018/1972) and a table whose cells hold
a line per row that does not line up (Richtlijn 2006/116/EG)."""

from __future__ import annotations

from lawgraph.core.concordance_html import read_tables
from lawgraph.core.succession import Place, SourceRow
from tests.paths import FIXTURES


def _tables(celex: str) -> list:
    html = (FIXTURES / f"eurlex_{celex.lower()}_concordance.html").read_text()
    return read_tables(html, celex)


def test_a_codification_names_its_old_act_and_reads_each_row() -> None:
    (table,) = _tables("32017R1001")
    assert table.name == (
        "BIJLAGE III Concordantietabel, Verordening (EG) nr. 207/2009"
    )
    assert (table.old_act, table.repealed, table.problem) == ("32009R0207", True, None)
    assert table.rows[:3] == (
        # a run placed in a run
        SourceRow(
            "1",
            "",
            Place("Artikelen 1 tot en met 7", "1", (), through="7"),
            "rij 1",
            "32017R1001",
            "7",
        ),
        SourceRow(
            "8",
            "leden 1 tot en met 4",
            Place("Artikel 8, leden 1 tot en met 4", "8", ("1", "2", "3", "4")),
            "rij 2",
            "32017R1001",
        ),
        SourceRow(
            "8",
            "lid 4 bis",
            Place("Artikel 8, lid 6", "8", ("6",)),
            "rij 3",
            "32017R1001",
        ),
    )
    # an article the old act got later, by its number in the table
    assert ("9 bis", "10") in {(r.old_article, r.place.article) for r in table.rows}


def test_a_recast_places_an_old_part_without_a_counterpart_in_no_article() -> None:
    (table,) = _tables("32019R0943")
    assert (table.old_act, table.repealed) == ("32009R0714", True)
    # "— | Artikel 1, onder a)": a new part without an old one gives no row
    assert table.rows[0].where == "rij 3"
    assert table.rows[0].old_article == "1"
    assert table.rows[0].part == "onder a)"
    assert table.rows[0].place == Place("Artikel 1, onder c)", "1", ())
    dropped = [r for r in table.rows if r.part == "lid 2, onder d)"]
    assert [r.place for r in dropped] == [Place("—", None, ())]


def test_a_table_of_several_old_acts_is_a_table_per_column() -> None:
    tables = _tables("32018L1972")
    assert [t.old_act for t in tables] == [
        "32002L0021",
        "32002L0020",
        "32002L0019",
        "32002L0022",
    ]
    assert {t.repealed for t in tables} == {True}
    by_act = {t.old_act: t.rows for t in tables}
    # each column gives its own rows, with the place of the column of this act
    assert [
        (r.old_article, r.part, r.place.text, r.place.leden)
        for r in by_act["32002L0020"]
    ] == [
        ("1", "", "Artikel 1, lid 1", ("1",)),
        ("2", "lid 1", "—", ()),
    ]
    assert [(r.old_article, r.place.leden) for r in by_act["32002L0019"]][0] == (
        "1",
        ("2", "3"),
    )
    # a bijlage of the old act gives no row
    assert [r.old_article for r in by_act["32002L0022"]] == ["1", "2"]
    assert by_act["32002L0021"][1] == SourceRow(
        "1", "lid 3 bis", Place("Artikel 1, lid 4", "1", ("4",)), "rij 2", "32018L1972"
    )


def test_lines_that_do_not_line_up_place_nothing_that_reads() -> None:
    """The cells of Richtlijn 2006/116/EG hold a line per row: 14 old, 13 new."""
    (table,) = _tables("32006L0116")
    assert table.old_act == "31993L0098"
    assert {r.place for r in table.rows} == {
        Place("13 lines of this act against 14", None, (), readable=False)
    }
    assert table.rows[1].old_article == "10"
    assert table.rows[1].part == "leden 1 tot en met 4"
    assert table.rows[1].where == "rij 1, regel 2"


def test_a_heading_without_a_table_and_a_recital_that_repeals_nothing() -> None:
    html = """<html><body>
    <div id="rct_5"><p>Richtlijn 2002/19/EG moet worden ingetrokken.</p></div>
    <p class="oj-doc-ti">BIJLAGE III</p><p>CONCORDANTIETABEL</p>
    <p>&gt;RUIMTE VOOR DE TABEL&gt;</p>
    <p class="oj-doc-ti">BIJLAGE IV</p><p>Concordantietabel</p>
    <table><tr><td><p>Richtlijn 2002/19/EG</p></td><td><p>Deze richtlijn</p></td></tr>
    <tr><td><p>Artikel 1</p></td><td><p>Artikel 3</p></td></tr></table>
    </body></html>"""
    missing, table = read_tables(html, "32018L1972")
    assert (missing.name, missing.problem) == (
        "BIJLAGE III CONCORDANTIETABEL",
        "no table in the HTML",
    )
    assert (table.old_act, table.repealed) == ("32002L0019", False)
    assert [r.place.article for r in table.rows] == ["3"]


def test_a_cell_with_more_references() -> None:
    html = """<html><body>
    <p>Concordantietabel</p>
    <table><tr><td><p>Richtlijn 79/409/EEG</p></td><td><p>Deze richtlijn</p></td></tr>
    <tr><td><p>Artikel 16, leden 1 en 2, en artikel 17, leden 2 en 3</p></td>
        <td><p>Artikel 6, lid 1, eerste en tweede alinea, en lid 3</p></td></tr>
    <tr><td><p>Artikelen 3 en 4</p></td><td><p>Artikel 11, lid 1 en bijlage V</p></td></tr>
    <tr><td><p>Bijlage I</p></td><td><p>Bijlage II</p></td></tr>
    </table></body></html>"""
    (table,) = read_tables(html, "32009L0147")
    assert [
        (r.old_article, r.part, r.place.article, r.place.leden) for r in table.rows
    ] == [
        ("16", "leden 1 en 2", "6", ("1",)),
        ("16", "leden 1 en 2", "6", ("3",)),
        ("17", "leden 2 en 3", "6", ("1",)),
        ("17", "leden 2 en 3", "6", ("3",)),
        ("3", "", "11", ("1",)),
        ("3", "", None, ()),
        ("4", "", "11", ("1",)),
        ("4", "", None, ()),
    ]
