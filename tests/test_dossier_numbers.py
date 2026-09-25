"""The dossiers of one number in the order of the Kamer, and what a user types for one."""

from __future__ import annotations

import pytest

from lawgraph.core.dossier_numbers import parse_dossier_query, suffix_sort_key


def test_the_dossiers_of_a_budget_are_in_the_order_of_the_kamer() -> None:
    suffixes = [
        "M",
        "XXIII",
        "IIB",
        "",
        "IXB",
        "A",
        "I",
        "IIA",
        "IX",
        "XVI",
        "III",
        "C",
    ]
    assert sorted(suffixes, key=suffix_sort_key) == [
        "",  # the Miljoenennota
        "I",
        "IIA",
        "IIB",
        "III",
        "IX",
        "IXB",
        "XVI",
        "XXIII",
        "A",  # the funds, after the chapters: L, C and M are funds, never numerals
        "C",
        "M",
    ]


def test_a_numbered_series_is_in_the_order_of_its_numbers() -> None:
    # by value: 02 < 7 < 31; a suffix of another form comes last
    assert sorted(["31", "02", "7", "", "(R1519)"], key=suffix_sort_key) == [
        "",
        "02",
        "7",
        "31",
        "(R1519)",
    ]


@pytest.mark.parametrize(
    ("text", "parsed"),
    [
        ("37035", ("37035", None)),
        (" 37035 ", ("37035", None)),
        ("37035-XXII", ("37035", "XXII")),
        ("37035 xxii", ("37035", "XXII")),
        ("21501-02", ("21501", "02")),
        ("23908-(R1519)", ("23908", "(R1519)")),
        ("Jeugdzorg", None),
        ("wet 2024", None),
        ("", None),
        (None, None),
    ],
)
def test_a_number_or_a_dossier_is_told_from_title_text(
    text: str | None, parsed: tuple[str, str | None] | None
) -> None:
    assert parse_dossier_query(text) == parsed


def test_a_second_reading_names_the_dossiers_of_its_first() -> None:
    from lawgraph.core.dossier_numbers import first_reading_dossiers

    memorandum = (
        "Met de bekendmaking van de wet van 14 oktober 2020 (Stb. 2020, 429) is de eerste "
        "lezing van dit grondwetsvoorstel afgerond. Voor de toelichting verwijzen wij naar "
        "de met betrekking tot de eerste lezing gewisselde stukken (Kamerstukken 35 418, "
        "Kamerstukken II 2019/20, 35 419, nr. 9, alsmede Handelingen II 2019/20, nr. 77)."
    )
    assert first_reading_dossiers(memorandum) == ["35418", "35419"]
    assert first_reading_dossiers("Zie Kamerstukken II 2019/20, 35 419, nr. 9.") == []


def test_the_order_of_a_dossier_is_the_order_of_the_kamer() -> None:
    from lawgraph.core.dossier_numbers import dossier_order

    labels = [
        ("37020", "XV"),
        ("36264", ""),
        ("37020", "IIA"),
        ("37020", ""),
        ("9999", ""),
    ]
    ordered = sorted(labels, key=lambda label: dossier_order(*label))
    assert ordered == [
        ("9999", ""),
        ("36264", ""),
        ("37020", ""),
        ("37020", "IIA"),
        ("37020", "XV"),
    ]


def test_the_short_title_is_what_the_title_ends_in_parentheses() -> None:
    from lawgraph.core.dossier_numbers import short_title

    assert short_title("Wijziging van de wet (Verzamelwet gegevensbescherming) ") == (
        "Verzamelwet gegevensbescherming"
    )
    assert short_title("Begroting (2027) van SZW") is None
    assert short_title(None) is None
