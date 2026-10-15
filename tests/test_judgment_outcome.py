"""How a judgment ended and what a conclusion proposes (``core/judgment_outcome.py``)."""

from __future__ import annotations

import pytest

from lawgraph.core.judgment_outcome import (
    conclusion_outcome,
    judgment_outcome,
    outcome_props,
)
from lawgraph.core.judgments import judgment_text, parse_judgment
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
