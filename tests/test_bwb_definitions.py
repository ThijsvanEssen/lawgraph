"""The definitions a regulation gives itself, read from its BWB XML (``core.bwb_definitions``).

The fixtures are articles of the toestanden the repository served on 9 October 2026, cut
out whole (the Wft article and two lists shortened): Besluit zorgverzekering art. 1, Wft
art. 1:1, Wet milieubeheer art. 8.47 and Vreemdelingenwet 2000 art. 1.
"""

from __future__ import annotations

from pathlib import Path

from lawgraph.core.bwb_definitions import (
    TermMatcher,
    applies,
    definition_ref,
    definitions,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str, bwb_id: str) -> list[dict]:
    return definitions(bwb_id, (FIXTURES / f"bwb_definitions_{name}.xml").read_text())


def test_a_list_of_terms_with_its_letters_and_the_regulation_wet_names() -> None:
    wet, verblijf, eigen_bijdrage, *_ = _read("bzv", "BWBR0018492")
    assert wet == {
        "article_key": "bwbr0018492_1",
        "article_number": "1",
        "term": "wet",
        "text": "de Zorgverzekeringswet",
        "place": "a",
        "jci": "jci1.3:c:BWBR0018492&hoofdstuk=1&artikel=1&o=a&z=2026-07-01&g=2026-07-01",
        "scope": {"kind": "besluit", "path": ""},
        # the definition is the law it links to
        "refers_to": "BWBR0018450",
    }
    assert (verblijf["term"], verblijf["text"]) == (
        "verblijf",
        "verblijf gedurende het etmaal",
    )
    # a definition that only cites an article of the law names no regulation
    assert eigen_bijdrage["refers_to"] is None


def test_terms_in_italics_one_after_another_as_the_wft_gives_them() -> None:
    found = _read("wft", "BWBR0020368")
    terms = [d["term"] for d in found]
    assert terms[:3] == ["aanbieden", "aanbieder", "aangewezen staat"]
    # the colon after the italics instead of in it: <nadruk>bieder</nadruk>: een …
    assert "bieder" in terms
    # a paragraph after a definition goes on with it
    (child,) = [d for d in found if d["term"] == "dochteronderneming"]
    assert child["text"].endswith("als dochteronderneming van de moederonderneming")
    # its meanings in the list after a term that stands alone
    (aanbieden,) = [d for d in found if d["term"] == "aanbieden"]
    assert aanbieden["text"].startswith(
        "a. het in de uitoefening van een beroep of bedrijf"
    )
    assert all(d["scope"] == {"kind": "wet", "path": ""} for d in found)


def test_definitions_of_a_paragraph_hold_in_that_paragraph_only() -> None:
    stortplaats = _read("wm", "BWBR0003245")[0]
    assert (stortplaats["term"], stortplaats["place"]) == ("stortplaats", "a")
    assert stortplaats["scope"] == {
        "kind": "paragraaf",
        "path": "/Hoofdstuk8/Paragraaf8.2",
    }
    assert applies(stortplaats, "/Hoofdstuk8/Paragraaf8.2/Artikel8.48")
    assert not applies(stortplaats, "/Hoofdstuk8/Paragraaf8.3/Artikel8.50")
    assert not applies(stortplaats, "/Hoofdstuk8/Paragraaf8.20/Artikel8.90")


def test_a_term_without_a_colon_is_left_out_and_a_regulation_without_any_gives_none() -> (
    None
):
    assert len(_read("vw2000", "BWBR0011823")) == 5
    plain = (
        '<toestand bwb-id="BWBR0000001"><wetgeving><wettekst>'
        '<artikel label="Artikel 1" bwb-ng-variabel-deel="/Artikel1"><kop><nr>1</nr></kop>'
        "<al>In deze wet wordt verstaan onder:</al><lijst><li><li.nr>a.</li.nr>"
        "<al>een onderdeel zonder begrip</al></li></lijst>"
        "<al>In deze wet wordt verstaan onder werkgever: de natuurlijke persoon.</al>"
        "</artikel></wettekst></wetgeving></toestand>"
    )
    assert [(d["term"], d["text"]) for d in definitions("BWBR0000001", plain)] == [
        ("werkgever", "de natuurlijke persoon.")
    ]


def test_the_terms_of_a_text_each_with_the_definition_that_holds_there() -> None:
    def defined(term: str, path: str = "", place: str = "a") -> dict:
        return {
            "article_key": "bwbr0000001_1",
            "term": term,
            "place": place,
            "scope": {"kind": "wet", "path": path},
        }

    matcher = TermMatcher(
        [
            defined("wet"),
            defined("eigen bijdrage", place="b"),
            defined("bijdrage", place="c"),
            defined("bijdrage", path="/Hoofdstuk2", place="d"),
        ]
    )
    text = "De Wet en de eigen bijdrage; een bijdrage, wetgeving, bijdragen."
    found = [
        (text[s:e], definition_ref(d))
        for s, e, d in matcher.find(text, "/Hoofdstuk1/Artikel3")
    ]
    # whatever its case; the longest term first; whole words only
    assert found == [
        ("Wet", "bwbr0000001_1:a"),
        ("eigen bijdrage", "bwbr0000001_1:b"),
        ("bijdrage", "bwbr0000001_1:c"),
    ]
    # in chapter 2 its own definition of the same term, the narrower one
    in_chapter = matcher.find("een bijdrage", "/Hoofdstuk2/Artikel9")
    assert [definition_ref(d) for _, _, d in in_chapter] == ["bwbr0000001_1:d"]
    assert TermMatcher([]).find("de wet", "") == []
