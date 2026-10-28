"""What a criminal judgment decided on the charge (``core/criminal_decision.py``)."""

from __future__ import annotations

from lawgraph.core.criminal_decision import CriminalDecision, criminal_decision


def _decision(*lines: str) -> CriminalDecision | None:
    rows = [{"id": "h", "kind": "heading", "text": "Beslissing"}]
    rows += [{"id": f"p-{n}", "kind": "body", "text": t} for n, t in enumerate(lines)]
    return criminal_decision(rows)


BOILERPLATE = (
    "Verklaart niet bewezen wat aan verdachte meer of anders is ten laste gelegd dan "
    "hiervoor is bewezen verklaard en spreekt verdachte daarvan vrij."
)


def test_a_conviction_with_the_formula_is_proven_not_partly() -> None:
    found = _decision(
        "De rechtbank:",
        "Verklaart bewezen dat verdachte het ten laste gelegde heeft begaan.",
        BOILERPLATE,
        "Verklaart het bewezene strafbaar.",
        "Verklaart verdachte daarvoor strafbaar.",
        "Veroordeelt verdachte tot een gevangenisstraf voor de duur van 3 (drie) jaren.",
        "Beveelt dat de tijd in voorlopige hechtenis in mindering wordt gebracht.",
    )
    assert found is not None
    assert found.proven == "ja"
    assert [(s.kind, s.amounts) for s in found.sentences] == [
        ("gevangenisstraf", ("3 jaren",))
    ]
    assert not found.several and not found.quashes


def test_an_acquittal_of_a_charge_beside_a_proven_one_is_partly() -> None:
    found = _decision(
        "Verklaart het onder 1 en 2 tenlastegelegde niet bewezen en spreekt de verdachte "
        "daarvan vrij.",
        "Verklaart bewezen dat de verdachte het onder 3 tenlastegelegde heeft begaan.",
        BOILERPLATE,
        "Verklaart het bewezene en de verdachte strafbaar.",
        "Veroordeelt de verdachte tot een taakstraf voor de tijd van 60 uren.",
    )
    assert found is not None and found.proven == "deels"
    assert found.sentences[0].kind == "taakstraf"


def test_a_full_acquittal_has_no_sentence() -> None:
    found = _decision(
        "Het hof:",
        "Vernietigt het vonnis waarvan beroep en doet opnieuw recht:",
        "Verklaart niet bewezen dat de verdachte het tenlastegelegde heeft begaan en spreekt "
        "de verdachte daarvan vrij.",
    )
    assert found is not None
    assert found.proven == "nee" and not found.sentences and found.quashes


def test_the_sentence_on_the_next_line_and_a_substitute_detention() -> None:
    found = _decision(
        "verklaart bewezen dat de verdachte het feit heeft begaan;",
        "veroordeelt de verdachte tot:",
        "een taakstraf voor de tijd van 60 (zestig) UREN;",
        "beveelt dat vervangende hechtenis zal worden toegepast voor 30 dagen;",
        "beveelt dat voorlopige hechtenis wordt afgetrokken;",
    )
    assert found is not None
    assert [s.kind for s in found.sentences] == ["taakstraf"]


def test_a_complaint_or_a_ruling_of_the_hoge_raad_is_no_verdict() -> None:
    assert _decision("De rechtbank verklaart het klaagschrift ongegrond.") is not None
    found = _decision("De rechtbank verklaart het klaagschrift ongegrond.")
    assert found is not None and found.proven is None and not found.sentences
    assert _decision("De Hoge Raad:", "Verwerpt het beroep.") is None
    hr = _decision("De Hoge Raad:", "Ontslaat de verdachte van alle rechtsvervolging.")
    assert hr is None


def test_two_sentences_and_the_prosecution_inadmissible_for_a_part() -> None:
    found = _decision(
        "Verklaart de officier van justitie niet-ontvankelijk in de vervolging van het onder "
        "2 ten laste gelegde.",
        "Verklaart bewezen dat verdachte het onder 1 en 3 heeft begaan.",
        "Veroordeelt de verdachte tot een gevangenisstraf van 60 dagen.",
        "Veroordeelt de verdachte tot een taakstraf van 120 uren.",
    )
    assert found is not None
    assert found.partly_inadmissible and found.several
    assert found.proven == "deels"


def test_a_sentence_only_ruling_of_the_court_of_appeal_says_nothing_on_proof() -> None:
    found = _decision(
        "Vernietigt het vonnis waarvan beroep maar alleen ten aanzien van de opgelegde straf.",
        "Veroordeelt de verdachte tot een gevangenisstraf voor de duur van 12 (twaalf) maanden.",
    )
    assert found is not None and found.proven is None
    assert found.sentences[0].amounts == ("12 maanden",)


def test_without_a_decision_there_is_none() -> None:
    assert (
        criminal_decision([{"id": "p", "kind": "body", "text": "Overwegingen."}])
        is None
    )
    assert criminal_decision(None) is None


def test_durations_in_words_and_digits() -> None:
    found = _decision(
        "Veroordeelt verdachte tot een gevangenisstraf voor de duur van 5 (vijf) jaren en "
        "tweeëntwintig maanden en een geldboete van € 1.500,00.",
    )
    assert found is not None
    assert found.sentences[0].kind == "meerdere"
    assert found.sentences[0].amounts == (
        "€ 1.500,00",
        "5 jaren",
        "tweeëntwintig maanden",
    )
