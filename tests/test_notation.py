"""The notations a person types for one thing, taken apart without a store."""

from __future__ import annotations

import pytest

from lawgraph.core.notation import (
    ArticleRef,
    LawMatch,
    Notation,
    NotationParser,
)

SR = "BWBR0001854"
SV = "BWBR0001903"
GW = "BWBR0001840"
AWB = "BWBR0005537"
BW3 = "BWBR0005291"
BW6 = "BWBR0005289"
BW7A = "BWBR0006000"
WRO = "BWBR0022481"
GDPR = "32016R0679"

CODES = {
    "Sr": SR,
    "Sv": SV,
    "Gw": GW,
    "Awb": AWB,
    "BW3": BW3,
    "BW6": BW6,
    "BW7A": BW7A,
    "AVG": GDPR,
}
NAMES = {
    "wetboek van strafrecht": [SR],
    "wetboek van strafvordering": [SV],
    "grondwet": [GW],
    "algemene wet bestuursrecht": [AWB],
    "wet ruimtelijke ordening": [WRO],
    "burgerlijk wetboek boek 6": [BW6],
    "burgerlijk wetboek boek 3": [BW3],
    "besluit ruimte": ["BWBR0000001", "BWBR0000002"],  # two laws, one name
}
PARSER = NotationParser(CODES, NAMES)


def parse(query: str) -> Notation | None:
    return PARSER.parse(query)


def article(law: str | None, number: str, qualifier: str | None = None) -> Notation:
    return Notation(
        kind="article", articles=(ArticleRef(law, number),), qualifier=qualifier
    )


# ── articles ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        # A code, with the keyword in its forms.
        ("artikel 287 Sr", article(SR, "287")),
        ("Artikel 287 SR", article(SR, "287")),
        ("art. 287 Sr", article(SR, "287")),
        ("art 287 Sr", article(SR, "287")),
        ("  art.   287   sr  ", article(SR, "287")),
        ("artikel 287 van het Wetboek van Strafrecht", article(SR, "287")),
        ("artikel 287 Wetboek van Strafrecht", article(SR, "287")),
        ("art. 1 Grondwet", article(GW, "1")),
        # Numbers as the graph stores them: letters, colon, dot.
        ("artikel 36e Sr", article(SR, "36e")),
        ("artikel 420bis Sr", article(SR, "420bis")),
        ("artikel 359a Sv", article(SV, "359a")),
        ("art. 3:4 Awb", article(AWB, "3:4")),
        ("art. 8:1 Awb", article(AWB, "8:1")),
        ("artikel 3.26 van de Wet ruimtelijke ordening", article(WRO, "3.26")),
        ("artikel 6.2.8 Wet ruimtelijke ordening", article(WRO, "6.2.8")),
        # The Burgerlijk Wetboek: the book leaves the number and picks the regulation.
        ("art. 6:162 BW", article(BW6, "162")),
        ("artikel 6:162 BW", article(BW6, "162")),
        ("artikel 6:162 van het BW", article(BW6, "162")),
        ("art. 6:162 bw", article(BW6, "162")),
        ("art. 3:40 BW", article(BW3, "40")),
        ("art. 7a:1576h BW", article(BW7A, "1576h")),
        ("art. 162 BW6", article(BW6, "162")),
        ("BW 6:162", article(BW6, "162")),
        # The law before the number.
        ("Sr 287", article(SR, "287")),
        ("sr 36e", article(SR, "36e")),
        ("Grondwet 1", article(GW, "1")),
        ("Wetboek van Strafrecht art 287", article(SR, "287")),
        ("Wetboek van Strafrecht artikel 287", article(SR, "287")),
        ("Awb 3:4", article(AWB, "3:4")),
        # Qualifiers are kept apart from the number.
        ("art. 6:162 lid 2 BW", article(BW6, "162", "lid 2")),
        ("artikel 287, derde lid, Sr", article(SR, "287", "derde lid")),
        ("art. 359a lid 1 onder b Sv", article(SV, "359a", "lid 1 onder b")),
        # The law as identifier, or as EU act.
        ("artikel 287 BWBR0001854", article(SR, "287")),
        ("artikel 5 32016R0679", article(GDPR, "5")),
        ("artikel 5 AVG", article(GDPR, "5")),
        # No law named: the number only.
        ("artikel 6", article(None, "6")),
        ("art. 6:162", article(None, "6:162")),
        ("art 36e", article(None, "36e")),
    ],
)
def test_an_article_is_read_with_the_number_as_the_graph_stores_it(
    query: str, expected: Notation
) -> None:
    assert parse(query) == expected


def test_an_enumeration_is_several_articles() -> None:
    parsed = parse("artikelen 36e en 36f Sr")
    assert parsed is not None
    assert parsed.articles == (ArticleRef(SR, "36e"), ArticleRef(SR, "36f"))


def test_an_enumeration_over_books_is_several_regulations() -> None:
    parsed = parse("artikelen 3:40 en 6:162 BW")
    assert parsed is not None
    assert parsed.articles == (ArticleRef(BW3, "40"), ArticleRef(BW6, "162"))


def test_the_book_is_not_an_article_of_its_own() -> None:
    parsed = parse("art. 6:162 BW")
    assert parsed is not None
    assert ArticleRef(None, "6") not in parsed.articles
    assert all(ref.number == "162" for ref in parsed.articles)


@pytest.mark.parametrize(
    "query",
    [
        "art. 999 Onbekende wet",  # a law nobody knows
        "art. 162 BW",  # BW is a family: without the book it names no regulation
        "art. 9:1 BW",  # there is no such book
        "artikel 287 Sr moord",  # the law is not what ends the text
        "Wetboek 287",  # too generic to be a law
        "moord",
        "Wetboek van Strafrecht",
        "",
        "   ",
    ],
)
def test_what_names_no_article_is_no_article(query: str) -> None:
    assert parse(query) is None


# ── identifiers ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("query", "kind", "identifier"),
    [
        ("ECLI:NL:HR:2023:123", "ecli", "ECLI:NL:HR:2023:123"),
        ("ecli:nl:hr:2023:123", "ecli", "ECLI:NL:HR:2023:123"),
        ("  ECLI:NL:RBAMS:2020:AB1234 ", "ecli", "ECLI:NL:RBAMS:2020:AB1234"),
        (
            "ECLI:CE:ECHR:2019:0101JUD001234510",
            "ecli",
            "ECLI:CE:ECHR:2019:0101JUD001234510",
        ),
        ("BWBR0001854", "bwb", "BWBR0001854"),
        ("bwbr0001854", "bwb", "BWBR0001854"),
        ("BWBV0001000", "bwb", "BWBV0001000"),
        ("32016R0679", "celex", "32016R0679"),
        ("32016r0679", "celex", "32016R0679"),
        ("32009L0128", "celex", "32009L0128"),
    ],
)
def test_an_identifier_is_recognised(query: str, kind: str, identifier: str) -> None:
    assert parse(query) == Notation(kind=kind, identifier=identifier)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "query",
    ["ECLI:NL:HR", "BWBR001854", "BWBX0001854", "32016R", "ECLI"],
)
def test_an_incomplete_identifier_is_not_one(query: str) -> None:
    assert parse(query) is None


# ── dossiers and papers ───────────────────────────────────────────────────────


def dossier(number: str, suffix: str | None = None) -> Notation:
    return Notation(kind="dossier", dossier=number, suffix=suffix)


def paper(number: str, sequence: str, suffix: str | None = None) -> Notation:
    return Notation(kind="document", dossier=number, suffix=suffix, sequence=sequence)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        # The dossier.
        ("36327", dossier("36327")),
        ("Kamerstuk 36327", dossier("36327")),
        ("kamerstuk 36327", dossier("36327")),
        ("Kamerstukken 36327", dossier("36327")),
        ("Kamerstuk II 36327", dossier("36327")),
        ("dossier 36327", dossier("36327")),
        ("36 327", dossier("36327")),
        ("Kamerstuk 36 327", dossier("36327")),
        ("29684-I", dossier("29684", "I")),
        ("29684-i", dossier("29684", "I")),
        ("Kamerstuk 29684-I", dossier("29684", "I")),
        ("Kamerstuk 35925 VII", dossier("35925", "VII")),
        ("Kamerstuk 1234", dossier("1234")),  # an old, shorter number needs the keyword
        # A paper in a dossier.
        ("36327-3", paper("36327", "3")),
        ("Kamerstuk 36327-3", paper("36327", "3")),
        ("Kamerstuk 36327 nr. 3", paper("36327", "3")),
        ("Kamerstuk 36327, nr. 3", paper("36327", "3")),
        ("Kamerstuk 36327, nr 3", paper("36327", "3")),
        ("Kamerstukken II 2020/21, 36327, nr. 3", paper("36327", "3")),
        ("Kamerstukken II 2020/2021, 36327, nr. 3", paper("36327", "3")),
        ("Kamerstukken I 2020/21, 36327, nr. 3", paper("36327", "3")),
        ("Kamerstuk 36 327 nr. 3", paper("36327", "3")),
        ("kst-36327-3", paper("36327", "3")),
        ("29684-I-3", paper("29684", "3", "I")),
        ("Kamerstuk 29684-I, nr. 3", paper("29684", "3", "I")),
        ("Kamerstuk I 35925, nr. A", paper("35925", "A")),
        ("Kamerstuk 36327 nr. 12", paper("36327", "12")),
    ],
)
def test_a_kamerstuk_is_a_dossier_or_a_paper_in_one(
    query: str, expected: Notation
) -> None:
    assert parse(query) == expected


@pytest.mark.parametrize(
    "query",
    [
        "2020",  # a year, not a dossier: too short without the keyword
        "1234",
        "123456",
        "36327 abc",
        "36 32",
        "Kamerstuk",
        "Kamerstuk abc",
        "36327 stikstof",
        "35925 VII",  # a suffix behind a space needs the keyword
        "3632-7",
    ],
)
def test_what_is_no_kamerstuk_is_none(query: str) -> None:
    assert parse(query) is None


# ── law names ─────────────────────────────────────────────────────────────────


def test_a_law_is_named_by_abbreviation_or_full_name() -> None:
    assert PARSER.law_matches("Sr")[0] == LawMatch(SR, "code")
    assert PARSER.law_matches("sr")[0] == LawMatch(SR, "code")
    assert PARSER.law_matches("Wetboek van Strafvordering")[0] == LawMatch(SV, "title")
    assert PARSER.law_matches("wetboek van strafvordering")[0] == LawMatch(SV, "title")
    assert PARSER.law_matches("de Grondwet")[0] == LawMatch(GW, "title")
    assert PARSER.law_matches("  Algemene  wet  bestuursrecht ")[0] == LawMatch(
        AWB, "title"
    )


def test_a_name_two_laws_share_lists_both() -> None:
    matches = PARSER.law_matches("Besluit ruimte")
    assert matches == [
        LawMatch("BWBR0000001", "title"),
        LawMatch("BWBR0000002", "title"),
    ]


def test_part_of_a_name_matches_by_prefix_or_by_containing_it() -> None:
    matches = PARSER.law_matches("wetboek van straf")
    assert matches == [LawMatch(SR, "prefix"), LawMatch(SV, "prefix")]
    contained = PARSER.law_matches("bestuursrecht")
    assert contained == [LawMatch(AWB, "contains")]


def test_a_full_name_comes_before_names_that_start_with_it() -> None:
    parser = NotationParser({}, {"wet ruimte": ["B"], "wet": ["A"]})
    assert parser.law_matches("wet") == [
        LawMatch("A", "title"),
        LawMatch("B", "prefix"),
    ]


@pytest.mark.parametrize("text", ["", "  ", "xyzzy", "za"])
def test_words_that_name_no_law_match_none(text: str) -> None:
    assert PARSER.law_matches(text) == []


def test_the_matches_are_capped() -> None:
    names = {f"wet nummer {n}": [f"BWBR{n:07d}"] for n in range(30)}
    assert len(NotationParser({}, names).law_matches("wet nummer")) == 6


def test_a_parser_without_laws_still_reads_identifiers_and_dossiers() -> None:
    empty = NotationParser({}, {})
    assert empty.parse("ECLI:NL:HR:2023:123") == Notation(
        kind="ecli", identifier="ECLI:NL:HR:2023:123"
    )
    assert empty.parse("Kamerstuk 36327-3") == paper("36327", "3")
    assert empty.parse("artikel 6") == article(None, "6")
    assert empty.parse("artikel 287 Sr") is None
    assert empty.law_matches("Grondwet") == []
