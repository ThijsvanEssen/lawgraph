"""An abbreviation in running text stands for a law as its source writes it.

"CBW" in a judgment is the Centrale Branchevereniging Wonen ("artikel 12 van de
CBW-voorwaarden"), not the Cyberbeveiligingswet, whose WTI abbreviation is "Cbw". Another
spelling ("AWB" for the Awb) stands for the law only in a text that also names it as its
source does. The sentences are from judgments of the Rechtspraak.
"""

from __future__ import annotations

import pytest

from lawgraph.core.citations import DutchCitationExtractor
from lawgraph.pipelines.semantic._detection import build_extractor

CBW, AWB, GW, SR = "BWBR0052872", "BWBR0005537", "BWBR0001840", "BWBR0001854"
AVG = "32016R0679"
CODES = {"Cbw": CBW, "Awb": AWB, "Gw": GW, "Sr": SR, "EVRM": "EVRM", "AVG": AVG}
INSTRUMENTS = {
    "Cyberbeveiligingswet": (CBW, None),
    "Algemene wet bestuursrecht": (AWB, None),
    "Grondwet": (GW, None),
}


def _cited(text: str, *, unknown_laws: bool = False) -> list[tuple[str | None, str]]:
    extractor = build_extractor(CODES, INSTRUMENTS)
    return [
        (hit.bwb_id or hit.celex or hit.unknown_law, hit.article_number or "")
        for hit in extractor.extract(text, unknown_laws=unknown_laws)
    ]


@pytest.mark.parametrize(
    "text",
    [
        "conform artikel 12 van de CBW-voorwaarden voor woonwinkels (2022) is de koper",
        "heeft daarop conform artikel 12 van de CBW voorwaarden annuleringskosten",
        "Op grond van artikel 11 van de CBW is de koper gehouden",
    ],
)
def test_an_other_spelling_is_not_the_law(text: str) -> None:
    assert _cited(text) == []


def test_an_other_spelling_is_a_law_the_graph_does_not_know() -> None:
    assert _cited("artikel 11 van de CBW is", unknown_laws=True) == [("CBW", "11")]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("de zorgplicht van artikel 21 van de Cbw geldt", [(CBW, "21")]),
        ("artikel 8:72 Awb", [(AWB, "8:72")]),
        ("artikel 120 Gw", [(GW, "120")]),
        ("artikel 287 Sr", [(SR, "287")]),
        # the first part of a compound: the article is still the law's
        ("het art. 6 EVRM-verweer is gevoerd", [("EVRM", "6")]),
        ("de art. 82 AVG-grondslag valt", [(AVG, "82")]),
        ("art. 4:6 Awb-regime", [(AWB, "4:6")]),
    ],
)
def test_the_spelling_of_the_source_is_the_law(
    text: str, expected: list[tuple[str, str]]
) -> None:
    assert _cited(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # the law by its name elsewhere in the text
        (
            "Gelet op de Algemene wet bestuursrecht. Ingevolge artikel 7:1 AWB is",
            [(AWB, "7:1")],
        ),
        # the law in the spelling of its source elsewhere in the text
        (
            "artikel 6:22 van de AWB is niet van toepassing; zie ook de Awb.",
            [(AWB, "6:22")],
        ),
    ],
)
def test_an_other_spelling_beside_the_law_is_the_law(
    text: str, expected: list[tuple[str, str]]
) -> None:
    assert _cited(text) == expected


def test_an_other_spelling_alone_is_not_the_law() -> None:
    assert _cited("artikel 120 van de GW treedt") == []


def test_a_query_is_read_in_any_case() -> None:
    """A search query (``core.notation``) is typed as it comes: "cbw 12" is the law."""
    extractor = DutchCitationExtractor(code_aliases=CODES)
    assert [
        (h.bwb_id, h.article_number) for h in extractor.extract("artikel 12 CBW")
    ] == [(CBW, "12")]
