"""Tests for detecting article references inside BWB texts."""

from lawgraph.pipelines.semantic.bwb_detect import (
    _MAX_ARTICLE_NUMBER,
    detect_bwb_article_citations,
)


def test_detect_single_article_reference() -> None:
    text = "Zie artikel 24c voor de van toepassing zijnde bepalingen."
    hits = detect_bwb_article_citations(text, "BWBR0001854")

    assert len(hits) == 1
    hit = hits[0]
    assert hit.article_number == "24c"
    assert hit.bwb_id == "BWBR0001854"
    assert hit.text == "24c"


def test_detect_multiple_references_in_one_phrase() -> None:
    text = "De artikelen 57 en 58 vormen een hoofdstuk."
    hits = detect_bwb_article_citations(text, "BWBR0001854")

    assert [hit.article_number for hit in hits] == ["57", "58"]


def test_detect_range_expands_to_intermediate_articles() -> None:
    text = "Artikel 57 tot en met 60 beschrijft een reeks bepalingen."
    hits = detect_bwb_article_citations(text, "BWBR0001854")

    numbers = [hit.article_number for hit in hits]
    assert set(numbers) == {"57", "58", "59", "60"}
    assert len(hits) == 4


def test_article_numbers_above_max_are_filtered() -> None:
    # Numbers larger than _MAX_ARTICLE_NUMBER are almost certainly years or fines,
    # not article numbers; they must not appear in the output.
    oversized = _MAX_ARTICLE_NUMBER + 1
    text = f"Zie artikel {oversized} voor de relevante bepalingen."
    hits = detect_bwb_article_citations(text, "BWBR0001854")
    assert all(
        int(h.article_number.split(".")[0]) <= _MAX_ARTICLE_NUMBER
        for h in hits
        if h.article_number.split(".")[0].isdigit()
    ), f"Expected no hits above {_MAX_ARTICLE_NUMBER}, got: {hits}"
    # Specifically, the oversized number should not be present.
    article_numbers = [h.article_number for h in hits]
    assert str(oversized) not in article_numbers
