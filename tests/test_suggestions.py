"""What a search that found nothing suggests instead (``core.suggestions``)."""

from __future__ import annotations

from lawgraph.core.suggestions import MOST, suggest, trigrams, vocabulary

VOCAB = vocabulary(
    [
        ("belastingschalen", "belastingschalen"),
        ("belastingschijven", "belastingschalen"),
        ("AI Act", "AI-verordening"),
    ],
    {"belasting": 40, "belastingen": 12, "coalitie": 3, "crisis": 5, "huur": 9},
)


def test_the_trigrams_are_those_of_pg_trgm() -> None:
    assert trigrams("cat") == {"  c", " ca", "cat", "at "}
    assert trigrams("ab cd") == {"  a", " ab", "ab ", "  c", " cd", "cd "}


def test_a_typo_suggests_the_name_it_is_like() -> None:
    assert suggest(VOCAB, "belastingschallen")[0] == "belastingschalen"
    assert suggest(VOCAB, "aiact") == ["AI Act"]


def test_a_concept_is_suggested_once_by_its_best_name() -> None:
    found = suggest(VOCAB, "belastingschijfen")
    assert found[0] == "belastingschijven"
    assert "belastingschalen" not in found


def test_one_word_of_two_words_of_the_titles_is_suggested_apart() -> None:
    assert suggest(VOCAB, "coalitiecrisis")[0] == "coalitie crisis"
    # a linking s between them
    assert suggest(VOCAB, "Belastingscrisis")[0] == "belasting crisis"
    # a part of four characters too, none of fewer
    assert suggest(VOCAB, "huurcrisis")[0] == "huur crisis"
    assert "wet crisis" not in suggest(
        vocabulary([], {"wet": 9, "crisis": 5}), "wetcrisis"
    )


def test_nothing_alike_suggests_nothing_and_never_the_query_itself() -> None:
    assert suggest(VOCAB, "xyzzy") == []
    assert "belasting" not in suggest(VOCAB, "Belasting")
    assert len(suggest(VOCAB, "belastingschalen")) <= MOST


def test_a_short_word_of_a_title_is_no_name() -> None:
    assert vocabulary([], {"kort": 1, "wet": 9}).names == ("kort",)
