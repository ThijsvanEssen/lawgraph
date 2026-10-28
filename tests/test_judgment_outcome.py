"""How a judgment ended and what a conclusion proposes (``core/judgment_outcome.py``)."""

from __future__ import annotations

import pytest

from lawgraph.core.judgment_metadata import parse_judgment
from lawgraph.core.judgment_outcome import (
    conclusion_outcome,
    judgment_outcome,
    outcome_props,
)
from lawgraph.core.judgment_paragraphs import judgment_text
from tests.paths import fixture_text


def _paragraphs(*rows: tuple[str, str]) -> list[dict[str, str]]:
    return [
        {"id": f"p-{n}", "kind": kind, "text": text}
        for n, (kind, text) in enumerate(rows, start=1)
    ]


URGENDA = _paragraphs(
    ("body", "Ook onderdeel 9 kan dus niet tot cassatie leiden."),
    ("heading", "Beslissing"),
    ("body", "De Hoge Raad:"),
    ("body", "- verwerpt het beroep;"),
    ("body", "- veroordeelt de Staat in de kosten van het geding in cassatie."),
    (
        "body",
        "Dit arrest is gewezen door de vicepresident C.A. Streefkerk als voorzitter.",
    ),
    ("subheading", "Lijst van gebruikte afkortingen"),
    ("body", "AR5 Fifth Assessment Report van het IPCC (2013 – 2014)"),
)


def test_the_first_clause_of_the_decision_says_how_it_ended() -> None:
    outcome = judgment_outcome(URGENDA)
    assert outcome is not None
    assert (outcome.label, outcome.text, outcome.paragraph_id) == (
        "verworpen",
        "verwerpt het beroep",
        "p-4",
    )


def test_a_quashing_with_a_referral_is_vernietigd_en_verwezen() -> None:
    paragraphs = _paragraphs(
        ("body", "5 Beslissing"),
        ("body", "De Hoge Raad:"),
        ("body", "verklaart het beroep in cassatie gegrond,"),
        ("body", "vernietigt de uitspraak van het Hof,"),
        ("body", "verwijst het geding naar het Gerechtshof te 's-Hertogenbosch, en"),
    )
    outcome = judgment_outcome(paragraphs)
    assert outcome is not None
    assert (outcome.label, outcome.text) == (
        "vernietigd en verwezen",
        "verklaart het beroep in cassatie gegrond",
    )


def test_partly_and_in_one_paragraph() -> None:
    paragraphs = _paragraphs(
        (
            "body",
            "7 Beslissing De Hoge Raad vernietigt de bestreden uitspraak, maar "
            "uitsluitend wat betreft de duur van de werkstraf; vermindert de werkstraf; "
            "verwerpt het beroep voor het overige.",
        ),
    )
    outcome = judgment_outcome(paragraphs)
    assert outcome is not None and outcome.label == "gedeeltelijk vernietigd"


def test_the_clauses_of_administrative_law_and_appeal() -> None:
    def label(clause: str) -> str | None:
        found = judgment_outcome(
            _paragraphs(
                ("heading", "BESLISSING"),
                ("subheading", "De Afdeling"),
                ("body", f"{clause};"),
            )
        )
        return found.label if found else None

    assert label("verklaart het hoger beroep gegrond") == "gegrond"
    assert label("verklaart het beroep van X B.V. ongegrond") == "ongegrond"
    assert label("verklaart het beroep niet‑ontvankelijk") == "niet-ontvankelijk"
    assert label("bevestigt de aangevallen uitspraak") == "bevestigd"
    assert label("bekrachtigt het vonnis waarvan beroep") == "bekrachtigd"
    assert label("wijst het verzoek af") == "afgewezen"
    assert label("wijst de vordering toe") == "toegewezen"
    # what no word says: a conviction, an interim decision
    assert label("verklaart bewezen dat de verdachte het feit heeft begaan") is None
    assert label("verwijst de zaak naar de rol van 3 juni 2014") is None


def test_without_a_decision_there_is_none() -> None:
    assert judgment_outcome(_paragraphs(("body", "Het middel faalt."))) is None
    assert judgment_outcome(None) is None


def test_what_a_conclusion_proposes() -> None:
    def proposal(sentence: str) -> str | None:
        found = conclusion_outcome(
            _paragraphs(
                ("heading", "7 Conclusie"),
                ("body", sentence),
                ("body", "AB Administratiefrechtelijke Beslissingen"),
            )
        )
        return found.label if found else None

    assert proposal("De conclusie strekt tot verwerping van het cassatieberoep.") == (
        "verwerping"
    )
    assert (
        proposal(
            "Deze conclusie strekt tot vernietiging van de bestreden uitspraak en tot "
            "terugwijzing van de zaak naar het hof."
        )
        == "vernietiging en verwijzing"
    )
    assert (
        proposal(
            "Ik geef de Hoge Raad in overweging het beroep in cassatie ongegrond te verklaren."
        )
        == "ongegrondverklaring"
    )
    # what it proposes follows the words that say it does
    assert (
        proposal(
            "Het middel in geen van zijn onderdelen gegrond bevindende concludeer ik tot "
            "verwerping van het beroep."
        )
        == "verwerping"
    )
    assert proposal("Het middel faalt.") is None


def test_the_props_of_a_conclusion_and_of_a_judgment() -> None:
    props = outcome_props("arrest", URGENDA)
    assert props["outcome"] == "verworpen" and props["conclusion_outcome"] is None
    conclusion = _paragraphs(
        ("body", "De conclusie strekt tot verwerping van het cassatieberoep.")
    )
    props = outcome_props("conclusie", conclusion)
    assert props["outcome"] is None
    assert props["conclusion_outcome"] == "verwerping"
    assert props["conclusion_outcome_paragraph_id"] == "p-1"


@pytest.mark.parametrize(
    ("name", "kind", "expected"),
    [
        # Urgenda: "De Hoge Raad: - verwerpt het beroep;"
        (
            "rechtspraak_hr_2019_2006_text.xml",
            "arrest",
            ("verworpen", "verwerpt het beroep"),
        ),
        ("rechtspraak_hr_2026_1357.xml", "arrest", ("gedeeltelijk vernietigd", None)),
        ("rechtspraak_rvs_2026_5682.xml", "uitspraak", ("bevestigd", None)),
        ("rechtspraak_rbmne_2026_3708.xml", "uitspraak", ("gegrond", None)),
        # an interim arrest: "splitst de onderhavige zaak", "houdt iedere verdere beslissing aan"
        ("rechtspraak_ghams_2026_2678.xml", "arrest", (None, None)),
        (
            "rechtspraak_phr_2026_901.xml",
            "conclusie",
            ("vernietiging en verwijzing", None),
        ),
        ("rechtspraak_phr_2023_1042.xml", "conclusie", ("ongegrondverklaring", None)),
    ],
)
def test_the_outcome_of_real_decisions(
    name: str, kind: str, expected: tuple[str | None, str | None]
) -> None:
    sections, _ = judgment_text(parse_judgment(fixture_text(name)))
    props = outcome_props(kind, sections)
    label = props["conclusion_outcome" if kind == "conclusie" else "outcome"]
    text = props["conclusion_outcome_text" if kind == "conclusie" else "outcome_text"]
    assert label == expected[0]
    if expected[1]:
        assert text == expected[1]


def _decision_of(*lines: str, heading: str = "Beslissing") -> list[dict[str, str]]:
    return _paragraphs(
        ("body", "Een overweging."),
        ("heading", heading),
        *[("body", line) for line in lines],
        (
            "body",
            "Aldus vastgesteld door mr. A, voorzitter, in tegenwoordigheid van mr. B.",
        ),
    )


# Real decisions of the Raad van State: the court under "Beslissing" is a heading itself.
_RVS_COURT_HEADING = [
    # ECLI:NL:RVS:2008:BG5315
    (
        "De Afdeling bestuursrechtspraak van de Raad van State",
        "bevestigt de aangevallen uitspraak.",
    ),
    # ECLI:NL:RVS:2009:BJ4585
    (
        "De voorzitter van de Afdeling bestuursrechtspraak van de Raad van State",
        "I. bevestigt de aangevallen uitspraak, voor zover aangevallen;",
    ),
]


@pytest.mark.parametrize(("court", "clause"), _RVS_COURT_HEADING)
def test_a_heading_naming_the_court_under_the_decision_is_not_its_end(
    court: str, clause: str
) -> None:
    paragraphs = _paragraphs(
        ("body", "Beslissing"),
        ("heading", court),
        ("body", "Recht doende in naam der Koningin:"),
        ("body", clause),
        ("body", "II. wijst het verzoek af."),
        (
            "body",
            "Aldus vastgesteld door mr. A, voorzitter, in tegenwoordigheid van mr. B.",
        ),
    )
    outcome = judgment_outcome(paragraphs)
    assert outcome is not None
    assert outcome.label == "bevestigd"
    assert outcome.paragraph_id == "p-4"


def test_another_heading_under_the_decision_still_ends_it() -> None:
    paragraphs = _paragraphs(
        ("heading", "Beslissing"),
        ("heading", "Lijst van gebruikte afkortingen"),
        ("body", "verwerpt het beroep"),
    )
    assert judgment_outcome(paragraphs) is None


def test_an_order_to_repair_a_defect_is_a_tussenuitspraak() -> None:
    # ECLI:NL:RVS:2010:BN4277 (bestuurlijke lus)
    paragraphs = _paragraphs(
        ("body", "Beslissing"),
        ("heading", "De Afdeling bestuursrechtspraak van de Raad van State"),
        ("body", "Recht doende in naam der Koningin:"),
        (
            "body",
            "draagt de raad van de gemeente Hoorn op om binnen drie maanden na de "
            "verzending van deze tussenuitspraak:",
        ),
        ("body", "bepaalt dat de vaststelling van een nieuw besluit niet behoeft;"),
    )
    outcome = judgment_outcome(paragraphs)
    assert outcome is not None
    assert outcome.label == "tussenuitspraak"
    assert outcome.paragraph_id == "p-4"
    # ECLI:NL:RBZWB:2024:3583
    outcome = judgment_outcome(
        _decision_of(
            "De rechtbank:",
            "draagt het college op binnen twee weken de rechtbank mee te delen of "
            "hij gebruik maakt van de gelegenheid de gebreken te herstellen;",
        )
    )
    assert outcome is not None and outcome.label == "tussenuitspraak"


def test_an_order_to_the_registry_is_no_tussenuitspraak() -> None:
    # ECLI:NL:GHAMS:2026:2678 starts with "splitst de zaak en draagt de griffie op"
    assert (
        judgment_outcome(
            _decision_of(
                "splitst de zaak en draagt de griffie van het hof op om partijen te "
                "informeren;",
                "houdt iedere verdere beslissing aan.",
            )
        )
        is None
    )


# Real decisions that had an outcome before the heading and the interim rules: they keep it.
@pytest.mark.parametrize(
    ("lines", "expected"),
    [
        # ECLI:NL:CRVB:1997:ZB7330
        (
            [
                "De Centrale Raad van Beroep,",
                "Recht doende:",
                "Bevestigt de aangevallen uitspraak voor zover aangevochten.",
            ],
            "bevestigd",
        ),
        # ECLI:NL:CRVB:1998:AA3445
        (
            [
                "De Centrale Raad van Beroep,",
                "Recht doende:",
                "Vernietigt de aangevallen uitspraak alsmede het bestreden besluit en "
                "verklaart het inleidend beroep alsnog gegrond;",
                "Bepaalt dat gedaagde een nader besluit neemt;",
            ],
            "vernietigd",
        ),
        # ECLI:NL:CRVB:1999:3
        (
            [
                "De Centrale Raad van Beroep,",
                "Recht doende:",
                "Verklaart het beroep ongegrond.",
            ],
            "ongegrond",
        ),
        # ECLI:NL:CRVB:2002:AF1317
        (
            [
                "De Centrale Raad van Beroep,",
                "Recht doende:",
                "Verklaart het beroep gegrond;",
                "Vernietigt het bestreden besluit;",
            ],
            "gegrond",
        ),
        # ECLI:NL:CRVB:2003:AH9040
        (
            [
                "De Centrale Raad van Beroep,",
                "Recht doende:",
                "Verklaart het hoger beroep niet-ontvankelijk voorzover betrekking hebbende "
                "op het besluit van 20 mei 1999;",
                "Bevestigt de aangevallen uitspraak voorzover betrekking hebbende op de "
                "besluiten van 25 juni 1999.",
            ],
            "niet-ontvankelijk",
        ),
        # ECLI:NL:CRVB:2016:3978
        (
            [
                "De Centrale Raad van Beroep:",
                "- vernietigt de aangevallen uitspraak;",
                "- wijst de zaak terug naar de rechtbank Amsterdam.",
            ],
            "vernietigd en verwezen",
        ),
        # ECLI:NL:CRVB:2020:782
        (
            ["De Centrale Raad van Beroep wijst het verzoek om herziening af."],
            "afgewezen",
        ),
        # ECLI:NL:RBMNE:2020:5604
        (
            [
                "De voorzieningenrechter:",
                "- wijst het verzoek om een voorlopige voorziening te treffen toe;",
                "- draagt verweerder op het betaalde griffierecht van € 178,- aan "
                "verzoekster te vergoeden;",
            ],
            "toegewezen",
        ),
    ],
)
def test_existing_outcomes_stay_the_same(lines: list[str], expected: str) -> None:
    outcome = judgment_outcome(_decision_of(*lines))
    assert outcome is not None and outcome.label == expected
