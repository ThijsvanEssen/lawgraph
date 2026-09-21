"""Characterization tests for the EU and TK citation detectors.

Both pipelines share one implementation of the EU citation patterns
(``lawgraph.core.eu_citations``) but keep their own confidence values and
article-number shape.  These tests pin what each caller produces so the
differences stay explicit.
"""

from __future__ import annotations

from lawgraph.core.citations import CitationHit
from lawgraph.pipelines.semantic.eurlex import detect_eu_citations
from lawgraph.pipelines.semantic.tk import detect_tk_citations

Sig = tuple[str, str | None, str | None, str | None, float]


def _sigs(hits: list[CitationHit]) -> set[Sig]:
    return {(h.kind, h.celex, h.bwb_id, h.article_number, h.confidence) for h in hits}


def _eu(text: str) -> set[Sig]:
    return _sigs(detect_eu_citations(text, {}))


def _tk(text: str) -> set[Sig]:
    return _sigs(detect_tk_citations(text, {}, {}))


# ---------------------------------------------------------------------------
# Article + directive / regulation
# ---------------------------------------------------------------------------


def test_eu_article_with_directive_confidence() -> None:
    assert ("article", "32010L0013", None, "6", 0.85) in _eu(
        "Artikel 6 van Richtlijn 2010/13/EU"
    )


def test_eu_article_with_regulation_confidence() -> None:
    assert ("article", "32016R0679", None, "12a", 0.85) in _eu(
        "artikel 12a van Verordening 2016/679"
    )


def test_eu_article_number_allows_one_letter_only() -> None:
    sigs = _eu("artikel 12ab van Richtlijn 2010/13/EU")
    assert not [s for s in sigs if s[0] == "article"]


def test_eu_article_does_not_accept_determiner_before_instrument() -> None:
    sigs = _eu("artikel 6 van de Richtlijn 2010/13/EU")
    assert not [s for s in sigs if s[0] == "article"]


def test_tk_article_with_besluit_confidence() -> None:
    assert ("article", "32011D0024", None, "5", 0.88) in _tk(
        "artikel 5 van het Besluit 2011/24/EU"
    )


def test_tk_article_number_allows_multiple_letters() -> None:
    assert ("article", "32011D0024", None, "12ab", 0.88) in _tk(
        "artikel 12ab van het Besluit 2011/24/EU"
    )


def test_tk_article_accepts_determiner_before_instrument() -> None:
    assert ("article", "32002F0584", None, "3", 0.88) in _tk(
        "artikel 3 van het Kaderbesluit 2002/584/JBZ"
    )


def test_tk_besluit_suffix_variants() -> None:
    assert ("article", "32011D0024", None, "5", 0.88) in _tk(
        "artikel 5 van het Besluit 2011/24/GBVB"
    )


def test_tk_keeps_the_article_hit_next_to_the_instrument_hit() -> None:
    sigs = _tk("artikel 6 van de Richtlijn 2010/13/EU")

    assert ("article", "32010L0013", None, "6", 0.88) in sigs
    assert ("instrument", "32010L0013", None, None, 0.65) in sigs


def test_eu_has_no_besluit_patterns() -> None:
    assert _eu("artikel 5 van het Besluit 2011/24/EU") == set()


# ---------------------------------------------------------------------------
# Instrument-level: literal CELEX, directive/regulation year+number, BWB id
# ---------------------------------------------------------------------------


def test_celex_literal_confidence_is_identical() -> None:
    expected = {("instrument", "32019L1158", None, None, 0.9)}
    assert _eu("zie celex:32019l1158 hierboven") == expected
    assert _tk("zie celex:32019l1158 hierboven") == expected


def test_directive_year_number_confidence_differs() -> None:
    assert _eu("Richtlijn 2010/64/EU") == {
        ("instrument", "32010L0064", None, None, 0.70)
    }
    assert _tk("Richtlijn 2010/64/EU") == {
        ("instrument", "32010L0064", None, None, 0.65)
    }


def test_regulation_year_number_confidence_differs() -> None:
    assert _eu("Verordening 2016/679") == {
        ("instrument", "32016R0679", None, None, 0.70)
    }
    assert _tk("Verordening 2016/679") == {
        ("instrument", "32016R0679", None, None, 0.65)
    }


def test_bare_bwb_id_confidence_differs_and_is_uppercased() -> None:
    assert _eu("zie bwbr0001854") == {("instrument", None, "BWBR0001854", None, 0.70)}
    assert _tk("zie bwbr0001854") == {("instrument", None, "BWBR0001854", None, 0.75)}


def test_bare_bwb_id_matches_treaty_ids() -> None:
    assert _eu("zie BWBV0001000") == {("instrument", None, "BWBV0001000", None, 0.70)}
    assert _tk("zie BWBV0001000") == {("instrument", None, "BWBV0001000", None, 0.75)}


def test_eu_alias_article_keeps_its_confidence() -> None:
    hits = detect_eu_citations("artikel 287 Sr", {"Sr": "BWBR0001854"})
    assert ("article", None, "BWBR0001854", "287", 0.95) in _sigs(hits)
