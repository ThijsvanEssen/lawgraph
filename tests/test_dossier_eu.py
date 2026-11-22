"""``core/dossier_eu.py`` and ``semantic tk-dossier-eu``: what the title of a dossier says
of the EU, and the acts its laws implement."""

from __future__ import annotations

import pytest

from lawgraph.core.dossier_eu import (
    com_celex_candidates,
    com_numbers,
    eu_ref,
    implements,
)
from lawgraph.pipelines.semantic.tk_dossier_eu import derived


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        (
            "EU-voorstellen: Omnibus I (CSRD & CSDDD) COM (2025) 80 en COM (2025) 81",
            ["COM(2025) 80", "COM(2025) 81"],
        ),
        (
            "EU-voorstel: Commissie Werkprogramma 2027 (COM(2026)710) (Engelstalige versie)",
            ["COM(2026) 710"],
        ),
        # the same document twice, once with leading zeros
        ("AccelerateEU (COM (2026) 370), COM(2026) 0370", ["COM(2026) 370"]),
        ("EU-voorstel tot opheffing EU-begrotingsmaatregelen tegen Hongarije", []),
        (None, []),
    ],
)
def test_com_numbers_of_a_title(title: str | None, expected: list[str]) -> None:
    assert com_numbers(title) == expected


def test_a_com_document_is_a_proposal_or_another_document() -> None:
    assert com_celex_candidates("COM(2025) 80") == ["52025PC0080", "52025DC0080"]


def test_eu_ref_takes_the_celex_the_graph_holds() -> None:
    title = "EU-voorstellen: COM (2025) 80 en COM (2025) 81"
    assert eu_ref(title, {"52025PC0080", "32016R0679"}) == [
        {"com": "COM(2025) 80", "celex": "52025PC0080"},
        {"com": "COM(2025) 81", "celex": None},
    ]
    assert eu_ref("Wijziging van de Wet X", set()) is None


def test_implements_from_the_title_and_the_laws_it_legislated() -> None:
    title = (
        "Wijziging van de Wet op het financieel toezicht ter implementatie van Richtlijn "
        "(EU) 2024/2811, ter uitvoering van Verordening (EU) 2024/2809"
    )
    assert implements(
        title, {"32024L2811": {"national_implementing_measure"}, "32019L1937": set()}
    ) == [
        {"celex": "32019L1937", "bases": []},
        {"celex": "32024L2811", "bases": ["national_implementing_measure", "title"]},
        {"celex": "32024R2809", "bases": ["title"]},
    ]


def test_an_act_the_title_amends_is_not_implemented() -> None:
    title = (
        "Wijziging van de Wet milieubeheer ter aanvullende implementatie van Richtlijn (EU) "
        "2018/851 van het Europees Parlement en de Raad van 30 mei 2018 tot wijziging van "
        "Richtlijn 2008/98/EG betreffende afvalstoffen"
    )
    assert implements(title, {}) == [{"celex": "32018L0851", "bases": ["title"]}]
    assert implements("Begroting Defensie 2027", {}) is None


def test_derived_merges_the_bases_of_every_edge() -> None:
    row = {
        "title": "EU-voorstel: Omnibus over belastingen COM (2026) 560",
        "legislated": [
            ["32016L1148", ["considerans"]],
            ["32016L1148", ["national_implementing_measure"]],
        ],
    }
    assert derived(row, set()) == {
        "eu_ref": [{"com": "COM(2026) 560", "celex": None}],
        "implements": [
            {
                "celex": "32016L1148",
                "bases": ["considerans", "national_implementing_measure"],
            }
        ],
    }
