"""The chamber of a judgment from its kop, and its main areas of law."""

from __future__ import annotations

import pytest

from lawgraph.core.judgment_chamber import chamber_of, chamber_of_kop
from lawgraph.core.judgment_metadata import subject_areas


@pytest.mark.parametrize(
    ("kop", "chamber"),
    [
        (
            ["HOGE RAAD DER NEDERLANDEN", "CIVIELE KAMER", "Nummer 19/00135"],
            "Civiele kamer",
        ),
        (["Hoge Raad", "Strafkamer", "nr. S 12/01234"], "Strafkamer"),
        (["HOGE RAAD", "BELASTINGKAMER", "Nr. 12/1"], "Belastingkamer"),
        (["HOGE RAAD", "Eerste Kamer", "Rek.nr. 1"], "Eerste Kamer"),
        (["GERECHTSHOF AMSTERDAM", "ONDERNEMINGSKAMER"], "Ondernemingskamer"),
        (["GERECHTSHOF", "Meervoudige Belastingkamer"], "Belastingkamer"),
        (
            [
                "GERECHTSHOF ARNHEM-LEEUWARDEN",
                "locatie Arnhem, afdeling civiel recht",
                "zaak",
            ],
            "Afdeling civiel recht",
        ),
        (["GERECHTSHOF", "Team Handel", "zaaknummer"], "Team Handel"),
        (
            ["RAAD VAN STATE", "AFDELING", "BESTUURSRECHTSPRAAK"],
            "Afdeling bestuursrechtspraak",
        ),
    ],
)
def test_a_kop_names_the_chamber(kop: list[str], chamber: str) -> None:
    assert chamber_of_kop(kop) == chamber


@pytest.mark.parametrize(
    "kop",
    [
        [],
        ["RECHTBANK AMSTERDAM"],
        ["RECHTBANK", "meervoudige kamer", "Nummer"],  # the bench, not a chamber
        [
            "RECHTBANK",
            "Bestuursrecht",
            "Zittingsplaats Roermond",
        ],  # an area, not a chamber
        [
            "HOGE RAAD",
            "Nummer 19/00135",
            "Datum 20 december 2019",
            "ARREST",
            "z",
            "x",
            "y",
            "Strafkamer",
        ],
    ],
)
def test_a_kop_that_names_none(kop: list[str]) -> None:
    assert chamber_of_kop(kop) is None


def test_the_chamber_is_read_from_the_first_paragraph() -> None:
    paragraphs = [
        {"text": "HOGE RAAD\n\nStrafkamer\n\nNummer 1"},
        {"text": "Civiele kamer"},
    ]
    assert chamber_of(paragraphs) == "Strafkamer"
    assert chamber_of([]) is None
    assert chamber_of(None) is None


def test_the_main_areas_of_law_are_each_subject_up_to_its_semicolon() -> None:
    assert subject_areas(
        ["Bestuursrecht; Belastingrecht", "Civiel recht", "Bestuursrecht", " ; x"]
    ) == ["Bestuursrecht", "Civiel recht"]
    assert subject_areas(None) == []
