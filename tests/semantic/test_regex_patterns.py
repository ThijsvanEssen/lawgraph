"""Tests for regex detection patterns used in semantic pipelines."""

from __future__ import annotations

import pytest

from lawgraph.pipelines.semantic.amendment_articles import (
    _KOMT_TE_LUIDEN,
    _VERVALT,
    _VERVANGEN_DOOR,
    _WORDT_GEWIJZIGD,
    _WORDT_INGEVOEGD,
    detect_amendment_citations,
)
from lawgraph.pipelines.semantic.citation_detect import format_celex

# ---------------------------------------------------------------------------
# Import the amendment patterns directly from the pipeline module
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Amendment pattern tests
# ---------------------------------------------------------------------------


class TestWordtGewijzigd:
    def test_wordt_gewijzigd_matches_basic_form(self) -> None:
        text = "Artikel 5 wordt als volgt gewijzigd:"
        assert _WORDT_GEWIJZIGD.search(text) is not None

    def test_wordt_gewijzigd_alternative_word_order(self) -> None:
        text = "Artikel 12 wordt gewijzigd als volgt:"
        assert _WORDT_GEWIJZIGD.search(text) is not None

    def test_wordt_gewijzigd_captures_article_number(self) -> None:
        text = "Artikel 42 wordt als volgt gewijzigd:"
        match = _WORDT_GEWIJZIGD.search(text)
        assert match is not None
        assert match.group(1) == "42"

    def test_wordt_gewijzigd_captures_alpha_suffix(self) -> None:
        text = "Artikel 5a wordt als volgt gewijzigd:"
        match = _WORDT_GEWIJZIGD.search(text)
        assert match is not None
        assert match.group(1) == "5a"

    def test_wordt_gewijzigd_case_insensitive(self) -> None:
        text = "artikel 7 wordt als volgt gewijzigd:"
        assert _WORDT_GEWIJZIGD.search(text) is not None

    def test_wordt_gewijzigd_does_not_match_unrelated(self) -> None:
        text = "De wet wordt niet gewijzigd op dit punt."
        assert _WORDT_GEWIJZIGD.search(text) is None


class TestVervalt:
    def test_vervalt_matches(self) -> None:
        text = "Artikel 5 vervalt."
        assert _VERVALT.search(text) is not None

    def test_vervalt_komt_te_vervallen(self) -> None:
        # The correct statutory Dutch phrase is "komt te vervallen".
        text = "Artikel 3 komt te vervallen"
        assert _VERVALT.search(text) is not None

    def test_vervalt_captures_article_number(self) -> None:
        text = "Artikel 18 vervalt."
        match = _VERVALT.search(text)
        assert match is not None
        assert match.group(1) == "18"

    def test_vervalt_alpha_suffix(self) -> None:
        text = "Artikel 6b vervalt."
        match = _VERVALT.search(text)
        assert match is not None
        assert match.group(1) == "6b"

    def test_vervalt_case_insensitive(self) -> None:
        text = "artikel 9 vervalt"
        assert _VERVALT.search(text) is not None


class TestWordtIngevoegd:
    def test_wordt_ingevoegd_matches(self) -> None:
        text = "Na artikel 5 wordt een nieuw artikel 5a ingevoegd"
        assert _WORDT_INGEVOEGD.search(text) is not None

    def test_wordt_ingevoegd_without_nieuw(self) -> None:
        text = "Na artikel 10 wordt een artikel 10a ingevoegd"
        assert _WORDT_INGEVOEGD.search(text) is not None

    def test_wordt_ingevoegd_captures_both_groups(self) -> None:
        text = "Na artikel 5 wordt een nieuw artikel 5a ingevoegd"
        match = _WORDT_INGEVOEGD.search(text)
        assert match is not None
        # group(1) is the reference article, group(2) is the new article
        assert match.group(1) == "5"
        assert match.group(2) == "5a"

    def test_wordt_ingevoegd_in_variant(self) -> None:
        text = "In artikel 7 wordt een nieuw artikel 7a ingevoegd"
        assert _WORDT_INGEVOEGD.search(text) is not None


class TestKomtTeLuiden:
    def test_komt_te_luiden_matches(self) -> None:
        text = "Artikel 5 komt te luiden:"
        assert _KOMT_TE_LUIDEN.search(text) is not None

    def test_komt_te_luiden_captures_article_number(self) -> None:
        text = "Artikel 22 komt te luiden:"
        match = _KOMT_TE_LUIDEN.search(text)
        assert match is not None
        assert match.group(1) == "22"

    def test_komt_te_luiden_alpha_suffix(self) -> None:
        text = "Artikel 3a komt te luiden:"
        match = _KOMT_TE_LUIDEN.search(text)
        assert match is not None
        assert match.group(1) == "3a"

    def test_komt_te_luiden_case_insensitive(self) -> None:
        text = "artikel 1 komt te luiden:"
        assert _KOMT_TE_LUIDEN.search(text) is not None


class TestVervangenDoor:
    def test_vervangen_door_matches(self) -> None:
        text = "In artikel 5 wordt 'groen' vervangen door 'blauw'."
        assert _VERVANGEN_DOOR.search(text) is not None

    def test_vervangen_door_captures_article_number(self) -> None:
        text = "In artikel 12 wordt de zinsnede 'X' vervangen door 'Y'."
        match = _VERVANGEN_DOOR.search(text)
        assert match is not None
        assert match.group(1) == "12"

    def test_vervangen_door_case_insensitive(self) -> None:
        text = "in artikel 3 wordt 'a' vervangen door 'b'."
        assert _VERVANGEN_DOOR.search(text) is not None


class TestDetectAmendmentCitations:
    """Integration tests for detect_amendment_citations()."""

    def test_returns_empty_for_blank_text(self) -> None:
        assert detect_amendment_citations("", "BWBR0001840") == []

    def test_returns_empty_for_blank_bwb_id(self) -> None:
        assert detect_amendment_citations("Artikel 5 vervalt.", "") == []

    def test_detects_wijzigt_relation(self) -> None:
        text = "Artikel 5 wordt als volgt gewijzigd: ..."
        from lawgraph.config.constants import RELATION_WIJZIGT

        results = detect_amendment_citations(text, "BWBR0001840")
        assert any(relation == RELATION_WIJZIGT for _, relation in results)

    def test_detects_trekt_in_relation(self) -> None:
        text = "Artikel 7 vervalt."
        from lawgraph.config.constants import RELATION_TREKT_IN

        results = detect_amendment_citations(text, "BWBR0001840")
        assert any(relation == RELATION_TREKT_IN for _, relation in results)

    def test_detects_introduceert_relation(self) -> None:
        text = "Na artikel 5 wordt een nieuw artikel 5a ingevoegd."
        from lawgraph.config.constants import RELATION_INTRODUCEERT

        results = detect_amendment_citations(text, "BWBR0001840")
        assert any(relation == RELATION_INTRODUCEERT for _, relation in results)

    def test_hit_carries_bwb_id(self) -> None:
        text = "Artikel 5 vervalt."
        results = detect_amendment_citations(text, "BWBR0001840")
        assert results
        hit, _ = results[0]
        assert hit.bwb_id == "BWBR0001840"

    def test_hit_confidence_voor_gewijzigd(self) -> None:
        text = "Artikel 5 wordt als volgt gewijzigd:"
        results = detect_amendment_citations(text, "BWBR0001840")
        assert results
        hit, _ = results[0]
        assert hit.confidence == pytest.approx(0.90)

    def test_hit_confidence_voor_vervalt(self) -> None:
        text = "Artikel 8 vervalt."
        results = detect_amendment_citations(text, "BWBR0001840")
        assert results
        hit, _ = results[0]
        assert hit.confidence == pytest.approx(0.80)

    def test_deduplication(self) -> None:
        # Same article + relation should only appear once
        text = "Artikel 5 vervalt. Artikel 5 vervalt."
        results = detect_amendment_citations(text, "BWBR0001840")
        trekt_in = [(h, r) for h, r in results if h.article_number == "5"]
        assert len(trekt_in) == 1


# ---------------------------------------------------------------------------
# CELEX format_celex tests
# ---------------------------------------------------------------------------


class TestFormatCelex:
    def test_format_celex_directive(self) -> None:
        assert format_celex("directive", "2010", "64") == "32010L0064"

    def test_format_celex_regulation(self) -> None:
        assert format_celex("regulation", "2016", "679") == "32016R0679"

    def test_format_celex_decision(self) -> None:
        """New C-category: decision."""
        assert format_celex("decision", "2002", "584") == "32002C0584"

    def test_format_celex_framework_decision(self) -> None:
        """New D-category: framework_decision."""
        assert format_celex("framework_decision", "2002", "584") == "32002D0584"

    def test_format_celex_pads_number_to_four_digits(self) -> None:
        assert format_celex("directive", "2000", "1") == "32000L0001"

    def test_format_celex_large_number(self) -> None:
        assert format_celex("regulation", "2021", "1119") == "32021R1119"

    def test_format_celex_invalid_number_falls_back_to_zero(self) -> None:
        result = format_celex("directive", "2010", "abc")
        assert result == "32010L0000"
