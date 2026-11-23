"""The numbers ``core.bwb_amounts`` reads from the text of an article: amounts, percentages,
time limits and dates as the BWB prints them (fragments of the IB 2001, the Awb, BW Boek 7,
the Wml and the Sr), and what it leaves out."""

from __future__ import annotations

from decimal import Decimal

from lawgraph.core.bwb_amounts import amounts


def _read(text: str, **structure: object) -> list[tuple[str, str, object, str]]:
    return [
        (
            text[a.found.start : a.found.end],
            a.found.kind,
            a.found.date if a.found.value is None else a.found.value,
            a.found.unit,
        )
        for a in amounts(text, **structure)  # type: ignore[arg-type]
    ]


def test_amounts_and_percentages_as_the_ib_prints_them() -> None:
    text = (
        "De algemene heffingskorting bedraagt € 3.115, verminderd met 6,398% van het "
        "gedeelte dat meer bedraagt dan € 29.736."
    )
    assert _read(text) == [
        ("€ 3.115", "bedrag", Decimal(3115), "EUR"),
        ("6,398%", "percentage", Decimal("6.398"), "%"),
        ("€ 29.736", "bedrag", Decimal(29736), "EUR"),
    ]


def test_the_notations_of_an_amount() -> None:
    text = (
        "maximaal € 102.000,00; een veelvoud van € 1.000,–; € 22,5 miljoen; de tweede "
        "categorie, € 3 350; 227 euro; vijftig procent; 20 procent"
    )
    assert [value for _, _, value, _ in _read(text)] == [
        Decimal(102000),
        Decimal(1000),
        Decimal(22500000),
        Decimal(3350),
        Decimal(227),
        Decimal(50),
        Decimal(20),
    ]


def test_a_time_limit_needs_a_word_that_makes_it_one() -> None:
    text = (
        "De termijn voor het indienen van een bezwaarschrift bedraagt zes weken. Binnen "
        "een termijn van twee maanden na de ontdekking; binnen 13 weken; ten minste "
        "achtentwintig dagen. Gevangenisstraf van ten hoogste negen jaren; van zestien "
        "jaar of ouder; arbeid van ten hoogste twaalf uur per week; zij bedraagt drie jaar."
    )
    assert [(t, v, u) for t, _, v, u in _read(text)] == [
        ("zes weken", Decimal(6), "week"),
        ("twee maanden", Decimal(2), "maand"),
        ("13 weken", Decimal(13), "week"),
        ("achtentwintig dagen", Decimal(28), "dag"),
    ]


def test_a_date_after_voor_per_or_met_ingang_van() -> None:
    text = (
        "vóór 1 april van het jaar; met ingang van 1 januari 2027; de Verordening van de "
        "Raad van 27 april 2016; per 31 februari 2020"
    )
    assert _read(text) == [
        ("1 april", "datum", "--04-01", "datum"),
        ("1 januari 2027", "datum", "2027-01-01", "datum"),
    ]


def test_what_is_in_doubt_is_not_read() -> None:
    text = "33 1/3% van het kapitaal; elfhonderd euro; per uur; 4 1/3 week"
    assert _read(text) == []


def test_a_redaction_gives_its_values_the_day_it_holds_from() -> None:
    text = "per uur € 10,60 per 1 juli 2026: € 14,99;"
    start = text.index("per 1")
    found = amounts(text, redactions=[{"start": start, "end": len(text) - 1}])
    assert [(a.found.value, a.source, a.valid_from) for a in found] == [
        (Decimal("10.60"), "text", None),
        (Decimal("14.99"), "redaction", "2026-07-01"),
    ]


def test_a_value_names_its_part_and_its_cell() -> None:
    text = "1. De tabel.\nI\tII\n-\t€ 38.883\n2. Binnen zes weken."
    parts = [
        {"id": "lid-1", "start": 3, "end": 30},
        {"id": "lid-2", "start": 34, "end": len(text)},
    ]
    tables = [{"start": 13, "end": 30}]
    found = amounts(text, parts=parts, tables=tables)
    assert [(a.part, a.cell) for a in found] == [("lid-1", (1, 1)), ("lid-2", None)]
    assert found[0].to_row()["value"] == "38883"
