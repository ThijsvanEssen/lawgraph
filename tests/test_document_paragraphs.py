"""The alineas of a Kamerstuk (``core/document_paragraphs.py``), on real papers of both dialects."""

from __future__ import annotations

import re
from typing import Any

from lawgraph.core.document_xml import parse_document_xml
from lawgraph.core.judgment_paragraphs import text_id
from tests.asserts import show_items
from tests.paths import fixture_text


def _paragraphs(name: str) -> tuple[str, list[dict[str, Any]]]:
    parsed = parse_document_xml(fixture_text(f"{name}.xml"))
    return parsed.text, parsed.paragraphs


def _rows(name: str) -> list[tuple[str, int | None, str]]:
    """``(kind, number, the first words)`` of each line of the paper *name*."""
    text, paragraphs = _paragraphs(name)
    return [
        (p["kind"], p["number"], text[p["char_start"] : p["char_end"]][:30])
        for p in paragraphs
    ]


def test_a_motion_numbers_what_it_holds_and_not_its_formula() -> None:
    # 37020 nr. 57: its alinea 4 is the first point of what it asks
    assert _rows("kst_37020_57") == [
        ("head", None, "GEWIJZIGDE MOTIE VAN DE LEDEN "),
        ("formula", None, "De Kamer,"),
        ("formula", None, "gehoord de beraadslaging,"),
        ("body", 1, "constaterende dat het aantal r"),
        ("body", 2, "overwegende dat een kleinere o"),
        ("body", 3, "verzoekt de regering voor de b"),
        ("body", 4, "– de Kamer te informeren over "),
        ("body", 5, "– adviescolleges, commissies, "),
        ("body", 6, "– Verkennen of rijkssubsidies "),
        ("formula", None, "en gaat over tot de orde van d"),
        ("formula", None, "Keijzer"),
        ("formula", None, "Kisteman"),
    ]


def test_a_motion_of_before_2010_has_its_name_and_date_in_its_head() -> None:
    # 29507 nr. 80: the title names the member in an element of its own, and the date
    # stands under it; its first overweging ends in a comma before "dat"
    rows = _rows("kst_29507_80")
    assert rows[:4] == [
        ("head", None, "BLANKSMA-VAN DE HEUVEL C.S."),
        ("head", None, "Voorgesteld 23 april 2009"),
        ("formula", None, "De Kamer,"),
        ("formula", None, "gehoord de beraadslaging,"),
    ]
    numbered = [(n, words) for kind, n, words in rows if n is not None]
    assert [n for n, _ in numbered] == [1, 2, 3, 4, 5, 6], show_items(rows)
    assert numbered[0][1].startswith("constaterende, dat")
    assert numbered[3][1].startswith("verzoekt de regering afstand")
    closing = next(i for i, row in enumerate(rows) if row[2].startswith("en gaat over"))
    assert {kind for kind, _, _ in rows[closing:]} == {"formula"}


def test_the_footnote_of_a_title_is_part_of_the_head() -> None:
    # 32467 nr. 14: "Vervanging in verband met wijziging van de ondertekening." is the note
    # on its title, not an alinea
    rows = _rows("kst_32467_14")
    assert [kind for kind, _, _ in rows[:2]] == ["head", "head"], show_items(rows[:4])
    assert rows[2] == ("body", 1, "De ondergetekenden stellen het")


def test_a_memorandum_numbers_its_text_and_not_its_headings() -> None:
    # 37020-I nr. 2 (the budget of the King): headings are no alinea, a table is one
    text, paragraphs = _paragraphs("kst_37020_i_2")
    first = paragraphs[0]
    assert (first["kind"], text[first["char_start"] : first["char_end"]]) == (
        "head",
        "MEMORIE VAN TOELICHTING",
    )
    headings = [p for p in paragraphs if p["kind"] == "heading"]
    assert headings and all(p["number"] is None for p in headings)
    assert text[headings[0]["char_start"] : headings[0]["char_end"]] == (
        "GERAAMDE UITGAVEN EN ONTVANGSTEN"
    )
    body = [p for p in paragraphs if p["kind"] == "body"]
    assert text[body[0]["char_start"] :].startswith("De begrotingsstaten die")
    assert body[0]["number"] == 1
    # Tabel 1 is one alinea, its title and its 14 rows, after the alinea before it
    lines = [p for p in paragraphs if p["kind"] == "table"]
    first_table = [p for p in lines if p["number"] == lines[0]["number"]]
    assert len(first_table) == 15, show_items(first_table)
    assert text[first_table[0]["char_start"] :].startswith("Tabel 1 Belangrijkste")
    assert "\t" in text[first_table[1]["char_start"] : first_table[1]["char_end"]]
    before = [p["number"] for p in paragraphs[: paragraphs.index(first_table[0])]]
    assert max(n for n in before if n) == first_table[0]["number"] - 1
    # the numbers run on without a gap
    numbers = list(dict.fromkeys(p["number"] for p in paragraphs if p["number"]))
    assert numbers == list(range(1, len(numbers) + 1))


def test_every_line_is_one_paragraph_with_its_offsets_into_the_text() -> None:
    for name in ("kst_37020_57", "kst_29507_80", "kst_37020_i_2", "kst_24138_3"):
        text, paragraphs = _paragraphs(name)
        lines = text.split("\n")
        assert [text[p["char_start"] : p["char_end"]] for p in paragraphs] == lines
        assert set(paragraphs[0]) == {"id", "number", "kind", "char_start", "char_end"}


def test_the_id_follows_the_text_and_tells_repeated_lines_apart() -> None:
    text, paragraphs = _paragraphs("kst_37020_i_2")
    ids = [p["id"] for p in paragraphs]
    assert len(set(ids)) == len(ids)
    malformed = [i for i in ids if not re.fullmatch(r"p-[0-9a-f]{8}(_\d+)?", i)]
    assert not malformed, show_items(malformed)
    first = paragraphs[0]
    assert first["id"] == text_id(text[first["char_start"] : first["char_end"]])
    repeated = [i for i in ids if "_" in i]
    assert repeated, "a budget repeats lines (Toelichting mutaties begroting 2027)"
    for later in repeated:
        base, seen = later.split("_")
        assert ids.index(base) < ids.index(later) and int(seen) >= 2


def test_a_paper_without_xml_structure_still_numbers_its_lines() -> None:
    xml = (
        "<officiele-publicatie><kamerstuk><stuk><titel>BRIEF</titel><algemeen>"
        "<vrije-tekst><al>Een.</al><al>Twee.</al></vrije-tekst></algemeen></stuk>"
        "</kamerstuk></officiele-publicatie>"
    )
    parsed = parse_document_xml(xml)
    assert [(p["kind"], p["number"]) for p in parsed.paragraphs] == [
        ("head", None),
        ("body", 1),
        ("body", 2),
    ]


def test_the_letter_of_an_amendment_part_opens_its_line() -> None:
    # the source gives "Ja" (a part inserted after J) as the number of the part, apart from
    # the line that says what it changes: one alinea, not a body line "Ja" of its own
    xml = fixture_text("kst_32467_14.xml").replace(
        '<lidnr status="officieel">I</lidnr>', '<lidnr status="officieel">Ja</lidnr>'
    )
    parsed = parse_document_xml(xml)
    lines = [parsed.text[p["char_start"] : p["char_end"]] for p in parsed.paragraphs]
    assert "Ja" not in lines, show_items(lines)
    assert "Ja Na artikel 7 wordt een artikel ingevoegd, luidende:" in lines, (
        show_items(lines)
    )
    assert any(line.startswith("II In artikel 13, eerste lid") for line in lines), (
        show_items(lines)
    )
