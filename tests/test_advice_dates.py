"""The days of an advice of the Raad van State, from the opening of its paper."""

from __future__ import annotations

from lawgraph.core.advice_dates import is_advice, read_advice_days

OPENING = (
    "ADVIES AFDELING ADVISERING RAAD VAN STATE EN NADER RAPPORT\n"
    "Hieronder zijn opgenomen het advies van de Afdeling advisering van de Raad van State "
    "d.d. 15 november 2023 en het nader rapport d.d. 2 februari 2024, aangeboden aan de "
    "Koning door de Minister van Binnenlandse Zaken en Koninkrijksrelaties.\n"
    "Blijkens de mededeling van 28 juni 2023 machtigde Uwe Majesteit ..."
)


def test_the_advice_and_the_nader_rapport_have_their_own_days() -> None:
    assert read_advice_days(OPENING) == {
        "advice_date": "2023-11-15",
        "report_date": "2024-02-02",
    }


def test_an_advice_without_a_nader_rapport_gives_only_its_day() -> None:
    text = "Advies van de Afdeling advisering van de Raad van State d.d. 21 april 2023, No. W1"
    assert read_advice_days(text) == {"advice_date": "2023-04-21", "report_date": None}


def test_a_text_without_the_opening_sentence_gives_no_day() -> None:
    assert read_advice_days("Algemeen\nDe Afdeling heeft geen bezwaar.") == {
        "advice_date": None,
        "report_date": None,
    }


def test_the_kinds_of_an_advice() -> None:
    assert is_advice("Advies Afdeling advisering Raad van State en Nader rapport")
    assert is_advice("Advies Afdeling advisering Raad van State")
    assert not is_advice("Advies van andere adviesorganen")
    assert not is_advice(None)
