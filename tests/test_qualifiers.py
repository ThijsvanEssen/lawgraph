"""Reading which lid, onderdeel or aanhef a citation names."""

from __future__ import annotations

import pytest

from lawgraph.core.citations import DutchCitationExtractor
from lawgraph.core.qualifiers import Qualifier, parse_qualifier, part_slug


def _q(
    leden: tuple[str, ...] = (), onderdelen: tuple[str, ...] = (), aanhef: bool = False
):
    return Qualifier(leden=leden, onderdelen=onderdelen, aanhef=aanhef)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # leden
        ("derde lid", _q(("3",))),
        ("eerste en tweede lid", _q(("1", "2"))),
        ("eerste, tweede en derde lid", _q(("1", "2", "3"))),
        ("eerste of tweede lid", _q(("1", "2"))),
        ("tweede tot en met vierde lid", _q(("2", "3", "4"))),
        ("tweede t/m vierde lid", _q(("2", "3", "4"))),
        ("eerste tot en met derde lid", _q(("1", "2", "3"))),
        ("2e lid", _q(("2",))),
        ("12de lid", _q(("12",))),
        ("twaalfde lid", _q(("12",))),
        ("lid 3", _q(("3",))),
        ("lid 2a", _q(("2a",))),
        ("Lid 3", _q(("3",))),
        ("leden 1 en 2", _q(("1", "2"))),
        ("leden 1, 2 en 4", _q(("1", "2", "4"))),
        ("leden 1 tot en met 3", _q(("1", "2", "3"))),
        ("lid 1 en lid 2", _q(("1", "2"))),
        ("eerste lid en tweede lid", _q(("1", "2"))),
        ("de leden 2 en 3", _q(("2", "3"))),
        ("eerste lid, eerste lid", _q(("1",))),
        # onderdelen
        ("onderdeel a", _q((), ("a",))),
        ("onder a", _q((), ("a",))),
        ("sub a", _q((), ("a",))),
        ("onder 2°", _q((), ("2",))),
        ("onder 2", _q((), ("2",))),
        ("onder 1º", _q((), ("1",))),
        ("onder a en b", _q((), ("a", "b"))),
        ("onder a of b", _q((), ("a", "b"))),
        ("onder a en onder b", _q((), ("a", "b"))),
        ("onderdelen c, d en e", _q((), ("c", "d", "e"))),
        ("onderdelen b tot en met d", _q((), ("b", "c", "d"))),
        ("onderdelen 2° en 3°", _q((), ("2", "3"))),
        ("onder aa", _q((), ("aa",))),
        # aanhef
        ("aanhef", _q((), (), True)),
        ("aanhef en onderdeel b", _q((), ("b",), True)),
        ("aanhef en onder c", _q((), ("c",), True)),
        # combinations, as the extractor captures them
        ("derde lid, onderdeel a", _q(("3",), ("a",))),
        ("eerste lid, onder 2°", _q(("1",), ("2",))),
        ("eerste lid, aanhef en onder c", _q(("1",), ("c",), True)),
        ("lid 2, onderdeel a", _q(("2",), ("a",))),
        ("eerste lid, aanhef", _q(("1",), (), True)),
        ("vierde lid, tweede volzin, aanhef en onder a", _q(("4",), ("a",), True)),
        # the text of a link in a regulation, article number and law included
        (
            "artikel 5, eerste lid, onder f, van de Wet digitale overheid",
            _q(("1",), ("f",)),
        ),
        ("artikel 9:17, onderdeel b", _q((), ("b",))),
        ("artikelen 4:17, vijfde lid, onder a en b", _q(("5",), ("a", "b"))),
        (
            "4:15, eerste lid, onderdeel b, tweede lid, onderdelen b en c, derde lid en vierde lid",
            _q(("1", "2", "3", "4"), ("b", "c")),
        ),
        (
            "Artikel 7:18, zesde lid, tweede volzin, zevende en achtste lid",
            _q(("6", "7", "8")),
        ),
        ("artikel\xa0193d lid\xa02", _q(("2",))),
        ("8:51c, aanhef en onderdelen b tot en met d", _q((), ("b", "c", "d"), True)),
        # nothing to read
        ("", _q()),
        (None, _q()),
        ("   ", _q()),
        ("artikel 5", _q()),
        ("artikel 6:162 van het Burgerlijk Wetboek", _q()),
        ("tweede volzin", _q()),
        ("laatste lid", _q()),
        ("lid", _q()),
        ("lid drie", _q()),
        ("onder", _q()),
        ("onder de wet", _q()),
        ("onder het volgende", _q()),
        ("onder in de wet", _q()),
        ("lidmaatschap", _q()),
        ("eerste lidstaat", _q()),
        ("artikel 5 lid 3:4", _q()),
        ("!!! ??? ,,, 123", _q()),
        ("\x00�\n\t", _q()),
    ],
)
def test_parse_qualifier(text, expected) -> None:
    assert parse_qualifier(text) == expected


def test_a_long_range_keeps_its_ends_only() -> None:
    assert parse_qualifier("leden 1 tot en met 100").leden == ("1", "100")


def test_a_backwards_range_keeps_its_ends_only() -> None:
    assert parse_qualifier("leden 5 tot en met 2").leden == ("5", "2")


def test_a_qualifier_is_empty_or_not() -> None:
    assert parse_qualifier("artikel 5").empty
    assert not parse_qualifier("aanhef").empty


def test_a_qualifier_round_trips_through_its_stored_form() -> None:
    qualifier = parse_qualifier("tweede lid, aanhef en onder a")

    assert Qualifier.from_dict(qualifier.to_dict()) == qualifier
    assert qualifier.to_dict() == {"leden": ["2"], "onderdelen": ["a"], "aanhef": True}


@pytest.mark.parametrize(
    "stored",
    [
        None,
        {},
        "x",
        5,
        {"leden": "1", "onderdelen": None, "aanhef": "yes"},
        {"leden": [None, [1]]},
    ],
)
def test_a_malformed_stored_qualifier_is_empty(stored) -> None:
    assert Qualifier.from_dict(stored).empty


@pytest.mark.parametrize(
    ("number", "slug"),
    [
        ("a", "a"),
        ("a.", "a"),
        ("1°.", "1"),
        ("1º", "1"),
        ("2a", "2a"),
        ("AA", "aa"),
        ("–", ""),
        ("", ""),
        (None, ""),
    ],
)
def test_part_slug(number, slug) -> None:
    assert part_slug(number) == slug


@pytest.mark.parametrize(
    ("sentence", "captured", "expected"),
    [
        ("artikel 10, tweede lid, Sr", "tweede lid", _q(("2",))),
        (
            "artikel 10, tweede lid, aanhef en onder a, Sr",
            "tweede lid, aanhef en onder a",
            _q(("2",), ("a",), True),
        ),
        ("artikel 3 onder c Opiumwet", "onder c", _q((), ("c",))),
        (
            "artikel 2, eerste lid, onderdeel b, Awb",
            "eerste lid, onderdeel b",
            _q(("1",), ("b",)),
        ),
        (
            "artikel 126aa, tweede lid, eerste volzin, van het Wetboek van Strafvordering",
            "tweede lid, eerste volzin",
            _q(("2",)),
        ),
        ("artikel 8:29 lid 1 en 2 Awb", "lid 1 en 2", _q(("1", "2"))),
        (
            "artikel 36e, eerste en tweede lid, Sr",
            "eerste en tweede lid",
            _q(("1", "2")),
        ),
    ],
)
def test_what_the_extractor_captures_is_read_back(sentence, captured, expected) -> None:
    """The raw qualifier of a hit (``CitationHit.qualifier``) is what a later step parses."""
    extractor = DutchCitationExtractor(
        code_aliases={"Sr": "BWBR0001854", "Awb": "BWBR0005537"},
        name_aliases={
            "Opiumwet": "BWBR0001941",
            "Wetboek van Strafvordering": "BWBR0001903",
        },
    )
    (hit, *_) = extractor.extract(sentence)

    assert hit.qualifier == captured
    assert parse_qualifier(hit.qualifier) == expected
