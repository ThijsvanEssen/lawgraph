"""Tests for detecting article references inside BWB texts."""

from lawgraph.pipelines.semantic.bwb_detect import detect_bwb_article_citations


def test_detect_single_article_reference() -> None:
    text = "Artikel 24c van het Wetboek van Strafrecht staat centraal."
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
