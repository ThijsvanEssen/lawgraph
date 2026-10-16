"""A law cited by its name: the longest run of words after the article that is the name of
a known law or of a family of books, as written in a text (brackets, a comma, quotes)."""

from __future__ import annotations

from lawgraph.core.citations import DutchCitationExtractor

BW6 = "BWBR0005289"
BW7 = "BWBR0005290"
CODES = {"BW6": BW6, "BW7": BW7}
NAMES = {
    "Wegenwet": "BWBR0001726",
    "Wet milieubeheer": "BWBR0003245",
    "Wet milieubeheer BES": "BWBR0028142",
    "Wet (BES) regeling": "BWBR0099998",
    "Burgerlijk Wetboek Boek 6": BW6,
    "Burgerlijk Wetboek Boek 7": BW7,
}


def _hits(
    text: str, names: dict[str, str] = NAMES
) -> list[tuple[str | None, str | None]]:
    extractor = DutchCitationExtractor(code_aliases=CODES, name_aliases=names)
    return [(h.bwb_id, h.article_number) for h in extractor.extract(text)]


def test_a_name_in_brackets_or_before_a_comma() -> None:
    assert _hits("artikel 4 (Wegenwet) bepaalt") == [("BWBR0001726", "4")]
    assert _hits("artikel 4 Wegenwet, eerste lid") == [("BWBR0001726", "4")]


def test_a_name_after_a_loose_quote() -> None:
    assert _hits("artikel 4 “ Wegenwet”") == [("BWBR0001726", "4")]
    assert _hits("artikel 4 'Wegenwet'.") == [("BWBR0001726", "4")]


def test_a_name_with_a_bracket_in_it() -> None:
    assert _hits("artikel 2 Wet (BES) regeling.") == [("BWBR0099998", "2")]


def test_the_name_of_a_book() -> None:
    assert _hits("artikel 669 Burgerlijk Wetboek Boek 7") == [(BW7, "669")]


def test_the_longest_name_wins() -> None:
    assert _hits("artikel 1.1 Wet milieubeheer BES geldt") == [("BWBR0028142", "1.1")]
    assert _hits("artikel 1.1 Wet milieubeheer geldt") == [("BWBR0003245", "1.1")]


def test_a_family_by_the_name_of_its_books() -> None:
    assert _hits("artikel 6:162 Burgerlijk Wetboek.") == [(BW6, "162")]


def test_a_law_of_the_name_of_a_family_is_the_law() -> None:
    names = {**NAMES, "Burgerlijk Wetboek": "BWBR0099999"}
    assert _hits("artikel 6:162 Burgerlijk Wetboek.", names) == [
        ("BWBR0099999", "6:162")
    ]


def test_no_known_name_is_no_hit() -> None:
    assert _hits("artikel 4 Onbekende wet") == []
