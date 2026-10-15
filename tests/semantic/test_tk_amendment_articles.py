"""``detect_amendment_citations``: the articles a text says it changes, each with its relation
and how sure the wording is."""

from __future__ import annotations

import pytest

from lawgraph.config.constants import (
    RELATION_AMENDS,
    RELATION_INTRODUCES,
    RELATION_REPEALS,
)
from lawgraph.pipelines.semantic.tk_amendment_articles import (
    detect_amendment_citations,
)

# Each wording of a change, with the hits it gives: (article, relation, confidence).
_WORDINGS = [
    # "wordt als volgt gewijzigd", in either word order
    ("Artikel 5 wordt als volgt gewijzigd:", [("5", RELATION_AMENDS, 0.90)]),
    ("Artikel 12 wordt gewijzigd als volgt:", [("12", RELATION_AMENDS, 0.90)]),
    ("Artikel 42 wordt als volgt gewijzigd:", [("42", RELATION_AMENDS, 0.90)]),
    ("Artikel 5a wordt als volgt gewijzigd:", [("5a", RELATION_AMENDS, 0.90)]),
    ("artikel 7 wordt als volgt gewijzigd:", [("7", RELATION_AMENDS, 0.90)]),
    ("De wet wordt niet gewijzigd op dit punt.", []),
    # "vervalt" and "komt te vervallen"
    ("Artikel 5 vervalt.", [("5", RELATION_REPEALS, 0.80)]),
    ("Artikel 3 komt te vervallen", [("3", RELATION_REPEALS, 0.80)]),
    ("Artikel 18 vervalt.", [("18", RELATION_REPEALS, 0.80)]),
    ("Artikel 6b vervalt.", [("6b", RELATION_REPEALS, 0.80)]),
    ("artikel 9 vervalt", [("9", RELATION_REPEALS, 0.80)]),
    # "wordt een (nieuw) artikel ... ingevoegd": the new article, not the one it follows
    (
        "Na artikel 5 wordt een nieuw artikel 5a ingevoegd",
        [("5a", RELATION_INTRODUCES, 0.85)],
    ),
    (
        "Na artikel 10 wordt een artikel 10a ingevoegd",
        [("10a", RELATION_INTRODUCES, 0.85)],
    ),
    (
        "In artikel 7 wordt een nieuw artikel 7a ingevoegd",
        [("7a", RELATION_INTRODUCES, 0.85), ("7", RELATION_AMENDS, 0.80)],
    ),
    # "komt te luiden"
    ("Artikel 5 komt te luiden:", [("5", RELATION_AMENDS, 0.85)]),
    ("Artikel 22 komt te luiden:", [("22", RELATION_AMENDS, 0.85)]),
    ("Artikel 3a komt te luiden:", [("3a", RELATION_AMENDS, 0.85)]),
    ("artikel 1 komt te luiden:", [("1", RELATION_AMENDS, 0.85)]),
    # "in artikel ... wordt ... vervangen door"
    (
        "In artikel 5 wordt 'groen' vervangen door 'blauw'.",
        [("5", RELATION_AMENDS, 0.80)],
    ),
    (
        "In artikel 12 wordt de zinsnede 'X' vervangen door 'Y'.",
        [("12", RELATION_AMENDS, 0.80)],
    ),
    ("in artikel 3 wordt 'a' vervangen door 'b'.", [("3", RELATION_AMENDS, 0.80)]),
]


@pytest.mark.parametrize(("text", "hits"), _WORDINGS)
def test_a_wording_of_a_change_gives_its_article_and_relation(
    text: str, hits: list[tuple[str, str, float]]
) -> None:
    assert [
        (hit.article_number, hit.relation, hit.confidence)
        for hit in detect_amendment_citations(text)
    ] == hits


def test_returns_empty_for_blank_text() -> None:
    assert detect_amendment_citations("") == []


def test_one_text_gives_each_article_and_relation_once() -> None:
    text = (
        "Artikel 5 wordt als volgt gewijzigd: a. In artikel 6 wordt 'x' vervangen "
        "door 'y'. Artikel 7 vervalt. Artikel 5 vervalt. Na artikel 8 wordt een "
        "nieuw artikel 8a ingevoegd. Artikel 9 komt te luiden: Artikel 7 vervalt."
    )
    assert [
        (hit.article_number, hit.relation, hit.confidence)
        for hit in detect_amendment_citations(text)
    ] == [
        ("5", RELATION_AMENDS, 0.90),
        ("8a", RELATION_INTRODUCES, 0.85),
        ("9", RELATION_AMENDS, 0.85),
        ("7", RELATION_REPEALS, 0.80),
        ("5", RELATION_REPEALS, 0.80),
        ("6", RELATION_AMENDS, 0.80),
    ]


def test_a_hit_carries_its_snippet() -> None:
    (hit,) = detect_amendment_citations("Artikel 5 vervalt.")
    assert hit.snippet == "Artikel 5 vervalt."
