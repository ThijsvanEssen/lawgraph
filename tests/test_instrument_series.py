"""Regulations renewed under one name are one series (a heuristic on their titles)."""

from __future__ import annotations

from lawgraph.core.instrument_series import Series, series_of, series_stem


def test_the_stem_is_the_title_without_its_years() -> None:
    assert series_stem("Mandaatbesluit DT&V 2022") == "mandaatbesluit dt&v"
    assert series_stem("Tarievenregeling 2023-2024") == "tarievenregeling"
    assert series_stem("Burgerlijk Wetboek Boek 7") is None  # no year
    assert series_stem("2024") is None  # nothing left
    assert series_stem(None) is None


def test_regulations_of_one_name_are_a_series_in_order_of_the_day_in_force() -> None:
    found = series_of(
        [
            (
                "bwbr0046339",
                "Mandaatbesluit DT&V 2022",
                "ministeriele-regeling",
                "2022-05-01",
            ),
            (
                "bwbr0044425",
                "Mandaatbesluit DT&V 2020",
                "ministeriele-regeling",
                "2020-03-01",
            ),
            (
                "bwbr0048317",
                "Mandaatbesluit DT&V 2024",
                "ministeriele-regeling",
                "2024-01-01",
            ),
            (
                "bwbr0000001",
                "Mandaatbesluit NOO 2022",
                "ministeriele-regeling",
                "2022-01-01",
            ),
            ("bwbr0000002", "Mandaatbesluit DT&V 2022", "wet", "2022-01-01"),
        ]
    )

    series_id = "ministeriele-regeling-mandaatbesluit-dt-en-v"
    assert found == {
        "bwbr0044425": Series(series_id, 1, 3),
        "bwbr0046339": Series(series_id, 2, 3),
        "bwbr0048317": Series(series_id, 3, 3),
    }  # a regulation with no sibling, or of another kind, is in none
