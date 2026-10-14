"""An abbreviation several laws have stands, in a dated text, for the law in force then.

The WTI gives "BRO" to the Besluit op de ruimtelijke ordening 1985 (in force 1986 to 1 July
2008) and "Bro" to the Besluit ruimtelijke ordening that replaced it (in force 1 July 2008 to
1 January 2024); "OW" to the Onteigeningswet (1851, still in force in part) and "Ow" to the
Omgevingswet (in force 1 January 2024). Neither law has the abbreviation first, so the date
of the judgment decides, then the spelling. A law no longer in force is not written in
another case without being named: "Hw" after 2003 is not the Huurwet ("HW").
"""

from __future__ import annotations

import pytest

from lawgraph.core.aliases import code_choices, law_dates
from lawgraph.core.bwb_wti import choose_short_titles, instrument_aliases
from lawgraph.core.citations import LawDates
from lawgraph.pipelines.semantic._detection import build_extractor

BRO_1985, BRO = "BWBR0003889", "BWBR0023798"
ONTEIGENINGSWET, OMGEVINGSWET = "BWBR0001842", "BWBR0037885"
HUURWET = "BWBR0002066"
# the WTI afkortingen, and the titles
WTI = {
    BRO_1985: (["BRO", "BRO 1985"], "Besluit op de ruimtelijke ordening 1985"),
    BRO: (["Bro"], "Besluit ruimtelijke ordening"),
    ONTEIGENINGSWET: (["OW"], "Onteigeningswet"),
    OMGEVINGSWET: (["Ow"], "Omgevingswet"),
    HUURWET: (["HW"], "Huurwet"),
}
# signed, in force, expired (the SRU: the day after the end of the last toestand)
DATES = {
    BRO_1985: LawDates("1985-12-02", "1986-03-01", "2008-07-01"),
    BRO: LawDates("2008-04-21", "2008-07-01", "2024-01-01"),
    ONTEIGENINGSWET: LawDates("1851-08-28", "1851-09-26"),
    OMGEVINGSWET: LawDates("2016-03-23", "2024-01-01"),
    HUURWET: LawDates("1950-12-13", "1951-01-01", "2003-08-01"),
}


def _codes() -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """The codes as ``normalize bwb`` and ``code_choices`` make them of the WTI."""
    abbreviations = {law: names for law, (names, _) in WTI.items()}
    short = choose_short_titles(abbreviations)
    aliases = instrument_aliases(abbreviations)
    return code_choices(
        {"bwb_id": law, "short_title": short[law], "aliases": aliases[law], "title": t}
        for law, (_, t) in WTI.items()
    )


def _cited(text: str, on: str | None) -> list[tuple[str | None, str]]:
    codes, shared = _codes()
    names = {title: (law, None) for law, (_, title) in WTI.items()}
    extractor = build_extractor(codes, names, law_dates=DATES, shared_codes=shared)
    return [
        (hit.bwb_id, hit.article_number or "") for hit in extractor.extract(text, on=on)
    ]


def test_the_abbreviations_several_laws_have_are_shared() -> None:
    codes, shared = _codes()
    assert shared == {
        "BRO": {BRO_1985: "BRO", BRO: "Bro"},
        "OW": {ONTEIGENINGSWET: "OW", OMGEVINGSWET: "Ow"},
    }
    assert codes == {"BRO 1985": BRO_1985, "HW": HUURWET}


@pytest.mark.parametrize(
    ("text", "on", "expected"),
    [
        # only the BRO 1985 was there: "Bro" is it, as it had been in force for years
        ("ingevolge artikel 19 Bro is vrijstelling verleend", "2005-03-02", BRO_1985),
        ("ingevolge artikel 19 BRO is vrijstelling verleend", "2005-03-02", BRO_1985),
        # the Bro replaced it on 1 July 2008
        ("gelet op artikel 3.1.6, eerste lid, van het Bro", "2010-06-09", BRO),
        ("gelet op artikel 3.1.6 Bro", "2008-07-01", BRO),
        # both expired: the one in force last
        ("gelet op artikel 3.1.6 Bro", "2025-02-12", BRO),
        # the Omgevingswet was signed in 2016, but in force in 2024
        ("de schadeloosstelling van artikel 40b Ow", "2020-11-04", ONTEIGENINGSWET),
        ("de schadeloosstelling van artikel 40b OW", "2020-11-04", ONTEIGENINGSWET),
        # both in force: as written
        ("het omgevingsplan van artikel 4.1 Ow", "2025-05-14", OMGEVINGSWET),
        ("de onteigening van artikel 72a OW", "2025-05-14", ONTEIGENINGSWET),
    ],
)
def test_a_shared_abbreviation_is_the_law_in_force_on_the_date(
    text: str, on: str, expected: str
) -> None:
    (cited,) = _cited(text, on)
    assert cited[0] == expected


def test_a_shared_abbreviation_of_a_law_no_longer_in_force_needs_its_name() -> None:
    """ "BRO" in 2025 is the BRO 1985 as written; beside the name of the Bro, the Bro."""
    assert _cited("artikel 3.1.6 BRO", "2025-02-12") == [(BRO_1985, "3.1.6")]
    named = "Het Besluit ruimtelijke ordening geldt. Artikel 3.1.6 BRO bepaalt"
    assert _cited(named, "2025-02-12") == [(BRO, "3.1.6")]


def test_an_undated_text_reads_no_shared_abbreviation() -> None:
    assert _cited("artikel 3.1.6 Bro", None) == []
    assert _cited("artikel 4.1 Ow", None) == []


def test_a_shared_abbreviation_is_no_law_before_any_of_them() -> None:
    assert _cited("artikel 19 Bro", "1980-01-01") == []


def test_a_text_that_defines_the_abbreviation_keeps_it() -> None:
    text = "artikel 1 van de Omgevingswet (hierna: Ow) en artikel 4.1 Ow"
    assert [law for law, _ in _cited(text, "2020-11-04")] == [OMGEVINGSWET] * 2


@pytest.mark.parametrize(
    ("text", "on", "expected"),
    [
        # in force: another case is the law
        ("artikel 28 Hw", "1999-04-01", [(HUURWET, "28")]),
        # repealed on 1 August 2003: another case is not the law
        ("artikel 28 Hw", "2020-04-01", []),
        # named so, or as written: the law, also after its repeal
        ("artikel 28 HW", "2020-04-01", [(HUURWET, "28")]),
        ("Onder de Huurwet gold: artikel 28 Hw", "2020-04-01", [(HUURWET, "28")]),
    ],
)
def test_another_case_of_a_law_no_longer_in_force_needs_its_name(
    text: str, on: str, expected: list[tuple[str, str]]
) -> None:
    assert _cited(text, on) == expected


def test_a_law_is_dated_until_it_expired() -> None:
    rows = [
        {
            "bwb_id": "bwbr0002066",
            "date_signed": "1950-12-13",
            "date_in_force": "1951-01-01",
            "date_expired": "2003-08-01",
        },
        {"bwb_id": BRO, "date_expired": "2024-01-01"},
    ]
    assert law_dates(rows) == {
        HUURWET: LawDates("1950-12-13", "1951-01-01", "2003-08-01"),
        BRO: LawDates(None, None, "2024-01-01"),
    }
