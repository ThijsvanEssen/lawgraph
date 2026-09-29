"""Unit tests for the semantic relationship type classifier."""

from __future__ import annotations

import pytest

from lawgraph.config.constants import (
    SEMANTIC_TYPE_CONDITIONAL_REQUIREMENT,
    SEMANTIC_TYPE_CROSS_REFERENCE,
    SEMANTIC_TYPE_DEFINITIONAL_REFERENCE,
    SEMANTIC_TYPE_DELEGATED_DISCRETION,
    SEMANTIC_TYPE_LIMITING_EXCEPTION,
    SEMANTIC_TYPE_PREREQUISITE_PROCEDURE,
    SEMANTIC_TYPE_SCOPE_LIMITATION,
)
from lawgraph.pipelines.semantic._relation_type_patterns import (
    ADJACENT,
    CONFIDENCE,
    CONFIDENCE_FALLBACK,
    WINDOW,
    classify_citation_context,
)


def _span(text: str, needle: str) -> tuple[int, int]:
    start = text.index(needle)
    return start, start + len(needle)


def test_definitional_reference_adjacent():
    text = "Een vergunning als bedoeld in artikel 5 wordt verleend door de raad."
    start, end = _span(text, "artikel 5")
    result = classify_citation_context(text, start, end)
    assert result is not None
    assert result.semantic_type == SEMANTIC_TYPE_DEFINITIONAL_REFERENCE
    assert result.confidence == CONFIDENCE[("definitional_reference", ADJACENT)]
    assert result.pattern == "definitional_reference_adjacent"


def test_conditional_requirement():
    text = "Dit verbod geldt alleen indien artikel 12 van toepassing is."
    start, end = _span(text, "artikel 12")
    result = classify_citation_context(text, start, end)
    assert result is not None
    assert result.semantic_type == SEMANTIC_TYPE_CONDITIONAL_REQUIREMENT


def test_limiting_exception():
    text = "In afwijking van artikel 8 kan de minister besluiten anders te handelen."
    start, end = _span(text, "artikel 8")
    result = classify_citation_context(text, start, end)
    assert result is not None
    assert result.semantic_type == SEMANTIC_TYPE_LIMITING_EXCEPTION


def test_limiting_exception_onverminderd():
    text = "Onverminderd artikel 3 blijft de verplichting bestaan."
    start, end = _span(text, "artikel 3")
    result = classify_citation_context(text, start, end)
    assert result is not None
    assert result.semantic_type == SEMANTIC_TYPE_LIMITING_EXCEPTION


def test_prerequisite_procedure():
    text = "Het besluit wordt genomen met inachtneming van artikel 7 van deze wet."
    start, end = _span(text, "artikel 7")
    result = classify_citation_context(text, start, end)
    assert result is not None
    assert result.semantic_type == SEMANTIC_TYPE_PREREQUISITE_PROCEDURE


def test_scope_limitation():
    text = "De artikelen 2 en 3 zijn niet van toepassing op de sectoren van bijlage I."
    start, end = _span(text, "artikelen 2")
    result = classify_citation_context(text, start, end)
    assert result is not None
    assert result.semantic_type == SEMANTIC_TYPE_SCOPE_LIMITATION


def test_what_an_article_names_defines_a_term():
    """ "genoemd in", "vermeld in": the vorderingen named in artikel 821, a definition by
    reference, not a limit of scope."""
    text = "De vorderingen, genoemd in artikel 821, doen een voorrecht ontstaan."
    start, end = _span(text, "artikel 821")
    result = classify_citation_context(text, start, end)
    assert result is not None
    assert result.semantic_type == SEMANTIC_TYPE_DEFINITIONAL_REFERENCE


def test_the_inverted_form_of_a_definition():
    text = "De in artikel 204, eerste lid, bedoelde periode is verstreken."
    start, end = _span(text, "artikel 204, eerste lid")
    result = classify_citation_context(text, start, end)
    assert result is not None
    assert result.semantic_type == SEMANTIC_TYPE_DEFINITIONAL_REFERENCE
    assert result.pattern == "definitional_reference_inverted_adjacent"
    assert "bedoelde" in result.explanation


def test_a_trigger_in_another_sentence_says_nothing():
    text = (
        "Het bestuur maakt dit bekend, voor zover de partijen hebben ingestemd. "
        "Artikel 107a is van overeenkomstige toepassing."
    )
    start, end = _span(text, "Artikel 107a")
    result = classify_citation_context(text, start, end)
    assert result is not None
    assert result.semantic_type == SEMANTIC_TYPE_CROSS_REFERENCE


def test_a_trigger_elsewhere_in_the_sentence_is_less_sure_than_one_before_it():
    text = (
        "Op een verzoek als bedoeld in lid 3 zijn in afwachting van de beslissing van de "
        "rechter de regels van artikel 612 van overeenkomstige toepassing."
    )
    start, end = _span(text, "artikel 612")
    result = classify_citation_context(text, start, end)
    assert result is not None
    assert result.pattern == "definitional_reference_window"
    assert result.confidence == CONFIDENCE[("definitional_reference", WINDOW)]
    assert result.confidence < CONFIDENCE[("definitional_reference", ADJACENT)]


def test_no_pattern_is_certain():
    assert all(0 < confidence < 1 for confidence in CONFIDENCE.values())


def test_delegated_discretion_in_window():
    text = (
        "Bij ministeriële regeling kunnen nadere regels worden gesteld "
        "over de toepassing van artikel 9."
    )
    start, end = _span(text, "artikel 9")
    result = classify_citation_context(text, start, end)
    assert result is not None
    assert result.semantic_type == SEMANTIC_TYPE_DELEGATED_DISCRETION


def test_plain_reference_falls_back_to_cross_reference():
    text = "De aanvraag bevat de gegevens, genoemd opzij van artikel 4."
    # Use a sentence without any trigger phrase at all:
    text = "De burgemeester stuurt een afschrift naar de raad over artikel 4."
    start, end = _span(text, "artikel 4")
    result = classify_citation_context(text, start, end)
    assert result is not None
    assert result.semantic_type == SEMANTIC_TYPE_CROSS_REFERENCE
    assert result.confidence == CONFIDENCE_FALLBACK


@pytest.mark.parametrize(
    ("start", "end"),
    [(None, 5), (5, None), (-1, 5), (10, 5), (0, 10_000)],
)
def test_invalid_spans_return_none(start, end):
    assert classify_citation_context("korte tekst", start, end) is None


def test_empty_text_returns_none():
    assert classify_citation_context("", 0, 1) is None


def test_explanation_mentions_matched_pattern():
    text = "Een inrichting als bedoeld in artikel 1.1 van de Wet milieubeheer."
    start, end = _span(text, "artikel 1.1")
    result = classify_citation_context(text, start, end)
    assert result is not None
    assert "als bedoeld in" in result.explanation.lower()
