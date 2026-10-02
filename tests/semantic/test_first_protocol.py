"""Article 1 of the First Protocol to the ECHR (BWBV0001001) as Dutch judgments cite it.

The sentences are taken from real judgments (tax and property cases). Its WTI gives no
abbreviation, so its aliases are kept by hand (``curated instrument-abbreviations``). "EP"
alone is no alias: it is also the Europees Parlement. A judgment that names the Protocol
"EP" itself ("(hierna: EP)") is followed in that judgment.
"""

from __future__ import annotations

import pytest

from lawgraph.core.aliases import code_aliases, curated_abbreviations
from lawgraph.core.citations import DutchCitationExtractor

EVRM, P1 = "BWBV0001000", "BWBV0001001"
ROWS = [
    {"bwb_id": EVRM, "short_title": "EVRM"},
    {"bwb_id": P1},  # no WTI abbreviation
    {"bwb_id": "BWBR0005290", "short_title": "BW7"},
]


def _ids(text: str) -> list[tuple[str | None, str]]:
    codes = code_aliases(ROWS, curated_abbreviations())
    hits = DutchCitationExtractor(code_aliases=codes).extract(text)
    return [(hit.bwb_id, hit.article_number) for hit in hits]


@pytest.mark.parametrize(
    "text",
    [
        # ECLI:NL:GHDHA:2021:1875 (box 3)
        "artikel 1 van het Eerste Protocol bij het EVRM",
        # ECLI:NL:HR:2017:2517
        "in strijd met artikel 1 EP EVRM. Dit is het geval indien die heffing",
        # ECLI:NL:PHR:2018:1439
        "een schending van artikel 1 EP bij het EVRM oplevert",
        # ECLI:NL:HR:2016:2888
        "beschermd door artikel 1 van het Eerste Protocol bij het Europees Verdrag tot "
        "bescherming van de rechten van de mens",
        "art. 1 Eerste Protocol EVRM",
        "artikel 1 Protocol nr. 1 bij het EVRM",
    ],
)
def test_the_first_protocol_by_its_names(text: str) -> None:
    assert _ids(text) == [(P1, "1")]


def test_a_judgment_that_names_it_ep_is_followed() -> None:
    # ECLI:NL:HR:2018:729
    text = (
        "komt het beroep van Allianz op de aansprakelijkheidslimiet van art. 8:983 lid 1 BW in "
        "strijd met art. 1 Eerste Protocol EVRM (hierna: EP) en is dit beroep naar maatstaven "
        "van redelijkheid en billijkheid onaanvaardbaar. Art. 1 EP heeft geen horizontale "
        "werking."
    )
    assert (P1, "1") in _ids(text)

    # ECLI:NL:RVS:2022:558: the name stands between the citation and the treaty
    text = (
        "een regulering van het gebruik van eigendom in de zin van artikel 1 van het eerste "
        "Protocol (hierna: EP) bij het Verdrag tot bescherming van de rechten van de mens. "
        "Voor zover zij een beroep doen op artikel 1 van het EP, faalt het betoog."
    )
    assert _ids(text) == [(P1, "1")]
    assert (
        len(
            DutchCitationExtractor(
                code_aliases=code_aliases(ROWS, curated_abbreviations())
            ).extract(text, every_occurrence=True)
        )
        == 2
    )


@pytest.mark.parametrize(
    "text",
    [
        # ECLI:NL:HR:2014:1523: "EP" alone, without a name the judgment gives it
        "dat om die reden deze wetgeving als geheel in strijd is met artikel 1 EP. 5.2.",
        # the Europees Parlement
        "Het Europees Parlement (hierna: het EP) stelt op grond van artikel 14 EP en artikel "
        "225 VWEU een verzoek op.",
        "Richtlijn 2008/104/EG van het Europees Parlement en de Raad; artikel 3 EP",
    ],
)
def test_ep_alone_is_no_first_protocol(text: str) -> None:
    assert (P1, "1") not in _ids(text)
    assert all(law != P1 for law, _ in _ids(text))


def test_the_echr_keeps_its_own_articles() -> None:
    assert _ids("artikel 14 EVRM in verbinding met artikel 1 EP EVRM") == [
        (EVRM, "14"),
        (P1, "1"),
    ]
