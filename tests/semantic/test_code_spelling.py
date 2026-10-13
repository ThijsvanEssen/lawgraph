"""An abbreviation in running text stands for a law as its source writes it.

"CBW" in a judgment is the Centrale Branchevereniging Wonen ("artikel 12 van de
CBW-voorwaarden"), not the Cyberbeveiligingswet, whose WTI abbreviation is "Cbw". Another
spelling ("AWB" for the Awb) stands for the law in a text that also names it as its source
does, or in a dated text once the law has been in force for years ("art. 8 Vw" for the
VW); never with a lower-case start ("bis" for BIS). A dated text cites no law that came to
be after it. The sentences are from judgments of the Rechtspraak.
"""

from __future__ import annotations

import pytest

from lawgraph.core.aliases import law_dates
from lawgraph.core.citations import DutchCitationExtractor, LawDates
from lawgraph.pipelines.semantic._detection import build_extractor

CBW, AWB, GW, SR = "BWBR0052872", "BWBR0005537", "BWBR0001840", "BWBR0001854"
VW, VB, AWR, WAHV = "BWBR0011823", "BWBR0011825", "BWBR0002320", "BWBR0004581"
BIS = "BWBR0002295"
AVG = "32016R0679"
# as the WTI writes them: the short title, and the other one-word abbreviations
CODES = {
    "Cbw": CBW,
    "Awb": AWB,
    "Gw": GW,
    "Sr": SR,
    "EVRM": "EVRM",
    "AVG": AVG,
    "VW": VW,
    "Vw 2000": VW,
    "VB": VB,
    "AWR": AWR,
    "Wahv": WAHV,
    "BIS": BIS,
}
INSTRUMENTS = {
    "Cyberbeveiligingswet": (CBW, None),
    "Algemene wet bestuursrecht": (AWB, None),
    "Grondwet": (GW, None),
    "Vreemdelingenwet 2000": (VW, None),
    "Vreemdelingenwet": (
        VW,
        None,
    ),  # without its year (``core.aliases.instrument_names``)
    "Besluit inlichtingen strafregisters": (BIS, None),
}
# signed, published or in force first; in force (the toestand of each law)
DATES = {
    CBW: LawDates("2026-07-08", "2026-08-15"),
    AWB: LawDates("1992-06-04", "1994-01-01"),
    VW: LawDates("2000-11-23", "2001-04-01"),
    VB: LawDates("2000-11-23", "2001-04-01"),
    AWR: LawDates("1959-07-02", "1962-10-01"),
    WAHV: LawDates("1989-07-03", "1992-09-01"),
    BIS: LawDates("1955-04-14", "1955-04-14"),
}


def _cited(
    text: str, *, unknown_laws: bool = False, on: str | None = None
) -> list[tuple[str | None, str]]:
    extractor = build_extractor(CODES, INSTRUMENTS, law_dates=DATES)
    return [
        (hit.bwb_id or hit.celex or hit.unknown_law, hit.article_number or "")
        for hit in extractor.extract(text, unknown_laws=unknown_laws, on=on)
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


@pytest.mark.parametrize(
    ("text", "on", "expected"),
    [
        (
            "gelet op hetgeen is bepaald in artikel 66a, eerste lid, Vw.",
            "2013-09-17",
            [(VW, "66a")],
        ),
        (
            "Artikel 12 van het Vb luidde ten tijde van belang:",
            "2007-02-14",
            [(VB, "12")],
        ),
        (
            "niet de vereiste aangifte heeft gedaan als bedoeld in artikel 27e, aanhef en "
            "onderdeel a, Awr.",
            "2009-03-18",
            [(AWR, "27e")],
        ),
        (
            "wat door de betrokkene op de voet van artikel 11 van de WAHV tot zekerheid is "
            "gesteld",
            "2015-09-28",
            [(WAHV, "11")],
        ),
    ],
)
def test_an_other_spelling_of_an_established_law_is_the_law(
    text: str, on: str, expected: list[tuple[str, str]]
) -> None:
    """A dated text writes the abbreviation of a law in force for years in its own case."""
    assert _cited(text, on=on) == expected


@pytest.mark.parametrize(
    ("text", "on"),
    [
        # the Centrale Branchevereniging Wonen, while the Cyberbeveiligingswet is new
        (
            "conform artikel 12 van de CBW-voorwaarden voor woonwinkels (2022)",
            "2026-07-22",
        ),
        ("Op grond van artikel 11 van de CBW is de koper gehouden", "2026-10-01"),
        # before the Cyberbeveiligingswet was signed: never that law, in any spelling
        ("artikel 10 van de CBW", "2000-12-12"),
        ("artikel 10 van de Cbw", "2000-12-12"),
        # the Vreemdelingenwet of 1965, not the Vreemdelingenwet 2000
        ("artikel 1a Vw", "1998-05-06"),
        ("artikel 1a van de Vreemdelingenwet", "1998-05-06"),
    ],
)
def test_a_law_that_is_new_or_not_yet_there_is_not_cited(text: str, on: str) -> None:
    assert _cited(text, on=on) == []


def test_a_law_named_in_a_text_after_it_came_to_be_is_cited() -> None:
    """The date only rules out the laws that came later: the Cbw cited as written."""
    assert _cited("de zorgplicht van artikel 21 Cbw", on="2026-09-01") == [(CBW, "21")]


@pytest.mark.parametrize(
    "text",
    [
        # "bis" numbers a lid of an EU regulation, not the Besluit inlichtingen strafregisters
        "Artikel 14, lid 5 bis, van Vo 987/2009, voor zover hier van belang, luidt:",
        "artikel 14 bis van het reglement",
    ],
)
def test_a_lower_case_spelling_is_never_the_law(text: str) -> None:
    assert _cited(text, on="2017-12-29") == []
    assert _cited(f"{text} Zie het Besluit inlichtingen strafregisters (BIS).") == []


def test_a_query_is_read_in_any_case() -> None:
    """A search query (``core.notation``) is typed as it comes: "cbw 12" is the law."""
    extractor = DutchCitationExtractor(code_aliases=CODES)
    assert [
        (h.bwb_id, h.article_number) for h in extractor.extract("artikel 12 CBW")
    ] == [(CBW, "12")]


def test_a_law_is_dated_by_its_source() -> None:
    """The earliest of signed, published and in force; in force, else that earliest day."""
    rows = [
        {
            "bwb_id": "bwbr0052872",
            "date_signed": "2026-07-08",
            "date_published": "2026-07-10",
            "date_in_force": "2026-08-15",
        },
        {
            "bwb_id": GW,
            "date_signed": None,
            "date_published": "",
            "date_in_force": "1840-09-12",
        },
        {"bwb_id": "BWBR0002066", "date_signed": "", "date_in_force": None},
        {"celex": AVG, "date_signed": "2016-04-27T00:00:00"},
    ]
    assert law_dates(rows) == {
        CBW: LawDates("2026-07-08", "2026-08-15"),
        GW: LawDates("1840-09-12", "1840-09-12"),
        AVG: LawDates("2016-04-27", "2016-04-27"),
    }
