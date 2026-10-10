"""Citations of a code that is split over books: ``artikel 6:162 BW``.

Every book of the Burgerlijk Wetboek is a regulation of its own (``CODE_FAMILIES``). The
book in front of the colon picks the regulation and is not part of the stored article
number, whichever books are loaded.
"""

from __future__ import annotations

from lawgraph.core.citations import DutchCitationExtractor
from lawgraph.pipelines.semantic.tk import detect_tk_citations

BW3 = "BWBR0005291"
BW6 = "BWBR0005289"
BW7 = "BWBR0005290"
BW7A = "BWBR0006000"
CODES = {"BW3": BW3, "BW6": BW6, "BW7": BW7, "BW7A": BW7A, "Sr": "BWBR0001854"}


def _hits(
    text: str, codes: dict[str, str] = CODES
) -> list[tuple[str | None, str | None]]:
    hits = DutchCitationExtractor(code_aliases=codes).extract(text)
    return [(h.bwb_id, h.article_number) for h in hits]


def test_book_in_the_number_picks_the_regulation() -> None:
    assert _hits("Zie artikel 6:162 BW.") == [(BW6, "162")]


def test_book_letter_and_article_letter() -> None:
    assert _hits("artikel 7a:1576h BW") == [(BW7A, "1576h")]


def test_abbreviated_keyword_and_qualifier() -> None:
    hits = DutchCitationExtractor(code_aliases=CODES).extract(
        "art. 7:658, tweede lid, BW"
    )
    assert [(h.bwb_id, h.article_number, h.qualifier) for h in hits] == [
        (BW7, "658", "tweede lid")
    ]


def test_enumeration_over_one_book() -> None:
    assert _hits("artikelen 3:305a en 3:305b BW") == [(BW3, "305a"), (BW3, "305b")]


def test_enumeration_over_books() -> None:
    assert _hits("artikelen 3:40 en 6:162 BW") == [(BW3, "40"), (BW6, "162")]


def test_van_het() -> None:
    assert _hits("artikel 6:162 van het BW") == [(BW6, "162")]


def test_family_is_case_insensitive() -> None:
    assert _hits("artikel 6:162 bw") == [(BW6, "162")]


def test_no_book_in_the_number_is_not_a_hit() -> None:
    assert _hits("artikel 162 BW") == []


def test_unknown_book_is_not_a_hit() -> None:
    assert _hits("artikel 9:1 BW") == []


def test_book_code_still_resolves_directly() -> None:
    assert _hits("artikel 162 BW6") == [(BW6, "162")]


def test_other_codes_are_unaffected() -> None:
    assert _hits("artikel 36e Sr") == [("BWBR0001854", "36e")]


def test_a_known_family_splits_even_when_registered_as_a_code() -> None:
    # Only Boek 7 loaded, whose short title was "BW": 6:162 is still book 6.
    codes = {"BW": BW7, "Sr": "BWBR0001854"}
    assert _hits("artikel 6:162 BW", codes) == [(BW6, "162")]
    assert _hits("artikel 7:658 BW", codes) == [(BW7, "658")]


def test_a_book_that_is_not_loaded_still_has_its_own_regulation() -> None:
    assert _hits("artikel 3:40 BW", {"Sr": "BWBR0001854"}) == [(BW3, "40")]


def test_the_tk_detector_resolves_the_family() -> None:
    hits = detect_tk_citations("op grond van artikel 6:162 BW", CODES, {})
    assert (BW6, "162") in {(h.bwb_id, h.article_number) for h in hits}


# The names of the books, as the graph has them (the citation titles in the BWB).
BOOK_NAMES = {
    "Burgerlijk Wetboek Boek 6": BW6,
    "Burgerlijk Wetboek Boek 7": BW7,
    "Wetboek van Strafrecht": "BWBR0001854",
}


def _named(text: str) -> list[tuple[str | None, str | None]]:
    hits = DutchCitationExtractor(code_aliases=CODES, name_aliases=BOOK_NAMES).extract(
        text
    )
    return [(h.bwb_id, h.article_number) for h in hits]


def test_the_name_of_the_family_from_the_names_of_its_books() -> None:
    # ECLI:NL:RBZWB:2026:1012 and :1100, which made no edge
    assert _named(
        "Artikel 7:669 lid 3 van het Burgerlijk Wetboek (hierna: BW) bepaalt dat"
    ) == [(BW7, "669")]
    assert _named("artikelen 7:17 en 7:18 van het Burgerlijk Wetboek (BW)") == [
        (BW7, "17"),
        (BW7, "18"),
    ]
    assert _named("artikel 6:162 Burgerlijk Wetboek.") == [(BW6, "162")]


def test_the_name_of_a_book_still_names_the_book() -> None:
    assert _named("artikel 669 Burgerlijk Wetboek Boek 7") == [(BW7, "669")]


def test_the_name_of_the_family_without_a_book_in_the_number_is_not_a_hit() -> None:
    assert _named("artikel 162 van het Burgerlijk Wetboek") == []
