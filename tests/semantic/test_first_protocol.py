"""Article 1 of the First Protocol to the ECHR (BWBV0001001) as Dutch judgments cite it.

The sentences are taken from real judgments (tax and property cases). Its WTI gives no
abbreviation, so its aliases are kept by hand (``curated instrument-abbreviations``). "EP"
alone is also the Europees Parlement: it is the Protocol in a judgment that also names the
EVRM or the Eerste Protocol (``in_context``), or that names the Protocol "EP" itself
("(hierna: EP)").
"""

from __future__ import annotations

import pytest

from lawgraph.core.aliases import (
    code_aliases,
    curated_abbreviations,
    curated_context_abbreviations,
)
from lawgraph.core.citations import DutchCitationExtractor

EVRM, P1 = "BWBV0001000", "BWBV0001001"
ROWS = [
    {"bwb_id": EVRM, "short_title": "EVRM"},
    {"bwb_id": P1},  # no WTI abbreviation
    {"bwb_id": "BWBR0005290", "short_title": "BW7"},
]


def _extractor() -> DutchCitationExtractor:
    context = {
        abbreviation: (law_id, words)
        for law_id, in_context in curated_context_abbreviations().items()
        for abbreviation, words in in_context.items()
    }
    return DutchCitationExtractor(
        code_aliases=code_aliases(ROWS, curated_abbreviations()),
        context_aliases=context,
    )


def _ids(text: str) -> list[tuple[str | None, str]]:
    return [(hit.bwb_id, hit.article_number) for hit in _extractor().extract(text)]


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


def test_ep_alone_in_a_judgment_that_names_the_evrm() -> None:
    # ECLI:NL:HR:2014:1523: "art. 1 EP" throughout, the EVRM named elsewhere
    text = (
        "Belanghebbende stelt dat de wetgeving in strijd is met het EVRM. "
        "Dat om die reden deze wetgeving als geheel in strijd is met artikel 1 EP. 5.2. "
        "Artikel 1 EP brengt onder meer mee dat een inbreuk op het recht op ongestoord "
        "genot van eigendom slechts is toegestaan indien een redelijke mate van evenredigheid "
        "bestaat."
    )
    assert _ids(text) == [(P1, "1")]
    assert len(_extractor().extract(text, every_occurrence=True)) == 2
    # the Eerste Protocol named in words elsewhere
    assert _ids("Het Eerste Protocol beschermt eigendom. Art. 1 EP is geschonden.") == [
        (P1, "1")
    ]


@pytest.mark.parametrize(
    "text",
    [
        # ECLI:NL:HR:2014:1523 without the rest of the judgment: nothing names the EVRM
        "dat om die reden deze wetgeving als geheel in strijd is met artikel 1 EP. 5.2.",
        # the Europees Parlement
        "Het Europees Parlement (hierna: het EP) stelt op grond van artikel 14 EP en artikel "
        "225 VWEU een verzoek op.",
        "Richtlijn 2008/104/EG van het Europees Parlement en de Raad; artikel 3 EP",
        # a word that merely contains the context ("EVRMX") is no context
        "Zie het EVRMX-rapport; artikel 1 EP.",
    ],
)
def test_ep_alone_without_the_evrm_is_no_first_protocol(text: str) -> None:
    assert all(law != P1 for law, _ in _ids(text))


def test_the_echr_keeps_its_own_articles() -> None:
    assert _ids("artikel 14 EVRM in verbinding met artikel 1 EP EVRM") == [
        (EVRM, "14"),
        (P1, "1"),
    ]


# ── whole judgments, as the orchestrator asked ───────────────────────────────


def test_a_judgment_that_quotes_art_1_ep_without_naming_the_evrm_has_no_edge() -> None:
    # ECLI:NL:PHR:2025:98 names neither the EVRM nor the Eerste Protocol anywhere
    text = (
        "De tarieven zijn verder niet zodanig hoog, ook niet indien de (relatieve) "
        "tariefstijging in ogenschouw wordt genomen, dat geconcludeerd moet worden dat op "
        "stelselniveau sprake is van een schending van artikel 1 EP.” 6.10 Ook het "
        "cassatieberoep tegen deze uitspraak is ongegrond verklaard."
    )
    assert _ids(text) == []


def test_a_judgment_that_also_names_the_europees_parlement_cites_the_protocol() -> None:
    # ECLI:NL:PHR:2021:98 (the opt-in system): the Europees Parlement, the EVRM and art. 1 EP
    text = (
        "dat uit een antwoord van Eurocommissaris Jourová op een vraag in het Europees "
        "Parlement volgt dat de Richtlijn OHP van toepassing is. "
        "Het betoog berust op artikel 1 Eerste Protocol bij het EVRM of algemene "
        "rechtsbeginselen. Ingevolge bestendige rechtspraak van het EHRM kan goodwill onder "
        "bepaalde omstandigheden weliswaar als eigendom in de zin van artikel 1 EP worden "
        "beschouwd."
    )
    hits = _extractor().extract(text, every_occurrence=True)
    assert [(h.bwb_id, h.article_number) for h in hits] == [(P1, "1"), (P1, "1")]


def test_a_box_3_judgment() -> None:
    # ECLI:NL:HR:2024:756 (box 3, rechtsherstel)
    text = (
        "De Inspecteur heeft aan belanghebbende voor de jaren 2017 en 2018 aanslagen in de "
        "inkomstenbelasting/premie volksverzekeringen opgelegd. Tijdens de procedure voor het "
        "Hof heeft de Hoge Raad het arrest van 24 december 2021, ECLI:NL:HR:2021:1963 "
        "gewezen, waaruit volgt dat een dergelijke heffing over de onderhavige jaren in strijd "
        "is met artikel 14 EVRM en artikel 1 EP indien daardoor belasting wordt geheven."
    )
    assert _ids(text) == [(EVRM, "14"), (P1, "1")]
