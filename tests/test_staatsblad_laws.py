"""A law of the Staatsblad the BWB does not hold, read from its publication: excerpts of the
XML of Stb. 2026, 56 (the Wetboek van Strafvordering) and Stb. 2026, 57 (the Tweede
vaststellingswet, which gives Boek 1, Hoofdstuk 10 and Boek 7 their text)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from lawgraph.api.schemas.completeness import completeness_dto
from lawgraph.core.bwb_definitions import TermMatcher
from lawgraph.core.staatsblad_laws import (
    LawPublication,
    article_props,
    law_completeness,
    law_definitions,
    law_props,
    law_text,
    number_span,
    own_references,
    publication_completeness,
    read_publication,
    read_records,
    unread_numbers,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def sv() -> LawPublication:
    law = read_publication(
        "stb-2026-56", (FIXTURES / "stb_2026_56_excerpt.xml").read_text()
    )
    assert law is not None
    return law


@pytest.fixture(scope="module")
def second() -> LawPublication:
    law = read_publication(
        "stb-2026-57", (FIXTURES / "stb_2026_57_excerpt.xml").read_text()
    )
    assert law is not None
    return law


def test_the_publication_says_its_law_dates_and_dossier(sv: LawPublication) -> None:
    assert sv.citation_title == "Wetboek van Strafvordering"
    assert sv.intitule.startswith("Wet van 25 februari 2026 tot vaststelling van het")
    assert (sv.date_signed, sv.date_published) == ("2026-02-25", "2026-03-13")
    assert sv.dossiers == ("36327",)


def test_a_law_with_articles_of_figures_enacts_one_an_amending_law_does_not(
    sv: LawPublication, second: LawPublication
) -> None:
    assert sv.enacts_a_law
    # ARTIKEL I-IIIA change, IV and V are its own articles, in Roman numerals
    assert not second.enacts_a_law
    assert second.dossiers == ("36636",)


def test_the_second_law_gives_whole_divisions_of_the_code_their_text(
    second: LawPublication,
) -> None:
    replaced = {(r.law, r.path) for r in second.replacements}
    assert replaced == {
        ("wetboek van strafvordering", (("boek", "1"), ("hoofdstuk", "10"))),
        ("wetboek van strafvordering", (("boek", "7"),)),
    }  # IIIA changes words of the Wetboek van Strafrecht: no division


def test_the_law_is_read_with_the_divisions_of_the_later_law_in_place(
    sv: LawPublication, second: LawPublication
) -> None:
    text = law_text(sv, [second])
    numbers = [a.number for a in text.articles]
    assert numbers == [
        "1.1.1",
        "1.1.2",
        "1.1.4",
        "1.5.1",
        "1.10.1",
        "1.11.1",
        "1.11.2",
        "2.8.6",
        "2.8.16",
        "7.1.1",
        "9.3",
    ]
    assert not text.not_found
    sources = {a.number: a.source for a in text.articles}
    assert sources["2.8.6"] == "stb-2026-56"
    assert sources["1.10.1"] == sources["7.1.1"] == "stb-2026-57"
    crumbs = {a.number: [c.to_dict() for c in a.breadcrumb] for a in text.articles}
    assert crumbs["2.8.6"] == [
        {"type": "boek", "label": "Boek 2", "title": "Het opsporingsonderzoek"},
        {
            "type": "hoofdstuk",
            "label": "Hoofdstuk 8",
            "title": "Heimelijke bevoegdheden",
        },
        {"type": "titeldeel", "label": "Titel 8.1", "title": "Algemene bepalingen"},
        {
            "type": "afdeling",
            "label": "Afdeling 8.1.6",
            "title": "Uitstel melding onbekende kwetsbaarheden",
        },
    ]
    assert [c["label"] for c in crumbs["1.10.1"]] == ["Boek 1", "Hoofdstuk 10"]
    assert [c["label"] for c in crumbs["7.1.1"]][:2] == ["Boek 7", "Hoofdstuk 1"]


def test_without_the_later_law_its_divisions_stay_empty(sv: LawPublication) -> None:
    numbers = [a.number for a in law_text(sv, []).articles]
    assert "1.10.1" not in numbers and "7.1.1" not in numbers


def test_the_props_of_the_law_and_an_article(
    sv: LawPublication, second: LawPublication
) -> None:
    props = law_props(sv, ["36327", "36636"])
    assert props["display_name"] == "Wetboek van Strafvordering (Stb. 2026, 56)"
    assert props["status"] == "vastgesteld" and props["in_force"] is False
    assert props["kind"] == "wet" and props["official_id"] == "stb-2026-56"
    article = next(a for a in law_text(sv, [second]).articles if a.number == "2.8.6")
    aprops = article_props(article, sv, 3)
    assert aprops["official_id"] == "stb-2026-56"
    assert aprops["display_name"] == (
        "Artikel 2.8.6 Wetboek van Strafvordering (Stb. 2026, 56)"
    )
    assert aprops["source_publication"] == "Stb. 2026, 56"
    assert aprops["text"].startswith("1. De officier van justitie kan")
    assert [p["id"] for p in aprops["parts"]] == ["lid-1", "lid-2"]


@pytest.mark.parametrize(
    ("text", "numbers"),
    [
        (
            "geautomatiseerd werk, bedoeld in artikel 2.8.16, wordt uitgesteld.",
            ["2.8.16"],
        ),
        ("de artikelen 1.1.1 en 1.1.2 zijn van toepassing", ["1.1.1", "1.1.2"]),
        ("artikel 3.1.1, eerste lid, van deze wet", ["3.1.1"]),
        ("artikel 76 van de Wet op de rechterlijke organisatie", []),
        ("artikel 41 Sr", []),
        ("artikel 24c van het Wetboek van Strafrecht", []),
        ("artikel 233 van Boek 1 van het Burgerlijk Wetboek", []),
        ("artikel 3, eerste lid, onderdeel d, van die wet", []),
        # an enumeration whose articles each have their parts, of another law
        (
            "de artikelen 98, eerste en tweede lid, 98c, eerste lid, 138ab, eerste tot en "
            "met derde lid, 161, aanhef en onder 1°, 161sexies, aanhef en onder 1°, en "
            "420bis, eerste lid, van het Wetboek van Strafrecht",
            [],
        ),
        # and of its own
        (
            "de artikelen 2.8.13, eerste lid, 2.8.15 en 2.8.16, tweede lid, zijn van "
            "toepassing",
            ["2.8.13", "2.8.15", "2.8.16"],
        ),
        # "van de officier van justitie" names no law
        (
            "een beslissing op grond van artikel 1.8.4, eerste lid, van de officier van "
            "justitie",
            ["1.8.4"],
        ),
    ],
)
def test_a_reference_to_an_article_of_the_own_law(
    text: str, numbers: list[str]
) -> None:
    assert [r.number for r in own_references(text)] == numbers


def test_a_reference_keeps_its_place_and_parts() -> None:
    text = "zoals bedoeld in artikel 3.1.1, eerste lid, van deze wet"
    (reference,) = own_references(text)
    assert text[reference.start : reference.end] == "3.1.1"
    assert reference.meta()["leden"] == ["1"]


def test_each_member_of_an_enumeration_has_its_own_parts() -> None:
    text = "de artikelen 2.8.13, eerste lid, 2.8.15 en 2.8.16, tweede lid, zijn"
    parts = {r.number: r.meta().get("leden") for r in own_references(text)}
    assert parts == {"2.8.13": ["1"], "2.8.15": [], "2.8.16": ["2"]}


def test_a_number_stands_where_the_text_writes_it() -> None:
    text = (
        "de artikelen 98, eerste lid, 98c en 161sexies van het Wetboek van Strafrecht"
    )
    start, end = number_span(text, 3, "98c") or (0, 0)
    assert text[start:end] == "98c"
    start, end = number_span(text, 3, "161sexies") or (0, 0)
    assert text[start:end] == "161sexies"
    assert number_span(text, 3, "99") is None


def test_a_citation_not_read_counts_its_numbers() -> None:
    text = "artikel 2.1.1 en de artikelen 5, eerste lid, en 6 van de Wet X"
    assert unread_numbers(text, []) == 3
    assert unread_numbers(text, [(8, 13)]) == 2


def test_each_article_has_its_place_as_the_bwb_names_it(sv: LawPublication) -> None:
    paths = {a.number: a.path for a in law_text(sv, []).articles}
    assert paths["1.11.1"] == "/Boek1/Hoofdstuk11/Titeldeel11.1/Artikel1.11.1"
    assert paths["2.8.6"] == (
        "/Boek2/Hoofdstuk8/Titeldeel8.1/Afdeling8.1.6/Artikel2.8.6"
    )
    article = next(a for a in law_text(sv, []).articles if a.number == "1.11.1")
    assert article_props(article, sv, 0)["path"] == article.path


def test_the_law_gives_its_definitions_each_where_it_holds(sv: LawPublication) -> None:
    found = law_definitions(sv, law_text(sv, []))
    by_term = {d["term"]: d for d in found}
    victim = by_term["slachtoffer"]
    assert victim["article_key"] == "stb_2026_56_1_5_1"
    assert victim["place"] == "a"
    assert victim["text"] == "het directe en het indirecte slachtoffer"
    # "In dit wetboek": the whole law; "In deze titel": Titel 11.1
    assert victim["scope"] == {"kind": "wetboek", "path": "", "reach": "own"}
    assert by_term["mediation"]["scope"]["path"] == "/Boek1/Hoofdstuk11/Titeldeel11.1"
    assert by_term["herstelrecht"]["place"] is None  # a dash is no place to cite
    assert len(found) == 8


def test_a_term_is_marked_where_its_definition_holds(sv: LawPublication) -> None:
    text = law_text(sv, [])
    matcher = TermMatcher(law_definitions(sv, text))
    article = {a.number: a for a in text.articles}
    terms = {
        number: {d["term"] for _, _, d in matcher.find(a.text, a.path or "")}
        for number, a in article.items()
    }
    assert terms["1.1.4"] == {"slachtoffer"}
    assert {"herstelrecht", "mediation", "slachtoffer"} <= terms["1.11.2"]
    # mediation holds in Titel 11.1 only
    outside = "Mediation is mogelijk."
    assert not matcher.find(outside, article["1.1.4"].path or "")


def test_the_stored_records_read_as_publications() -> None:
    xml = (FIXTURES / "stb_2026_56_excerpt.xml").read_text()
    found, skipped = read_records(
        [("stb-2026-56", xml), ("stb-2026-9", None), ("stb-2026-8", "<a>")]
    )
    assert [p.official_id for p in found] == ["stb-2026-56"]
    assert skipped == [
        ("no XML", "stb-2026-9"),
        ("XML that does not parse", "stb-2026-8"),
    ]


@pytest.mark.parametrize(
    ("article", "law", "expected"),
    [
        (
            {},
            {},
            {"references": {"state": "pending"}, "definitions": {"state": "pending"}},
        ),
        (
            {"unlinked_references": 0},
            {"definitions_found": 0},
            {"references": {"state": "done"}, "definitions": {"state": "done"}},
        ),
        (
            {"unlinked_references": 2},
            {"definitions_found": 29},
            {
                "references": {"state": "partial", "missing": 2},
                "definitions": {"state": "done"},
            },
        ),
    ],
)
def test_what_the_pipeline_made_of_a_law(
    article: dict[str, int], law: dict[str, int], expected: dict[str, Any]
) -> None:
    props = {"source": "staatsblad", "kind": "wet", **law}
    assert law_completeness(article, props) == expected
    assert law_completeness({**props, **article}) == expected


def test_a_law_of_the_bwb_has_no_completeness_of_the_staatsblad() -> None:
    assert law_completeness({"source": "bwb", "kind": "wet"}) is None
    publication = {"source": "staatsblad", "kind": "publicatie"}
    assert law_completeness(publication) is None


@pytest.mark.parametrize("series", ["Stb", "Stcrt", "Trb"])
def test_a_publication_the_bwb_names_has_its_text_not_fetched(series: str) -> None:
    """Officielebekendmakingen.nl holds its text; what it changes is read from the BWB."""
    props = {"source": "bwb", "kind": "publicatie", "publication_kind": series}
    assert publication_completeness(props) == {"text": {"state": "not_fetched"}}


def test_a_publication_of_a_law_the_staatsblad_retrieve_fetched_says_nothing() -> None:
    """Its XML is fetched: the law it enacts is read from it (``wet_stb_2026_56``)."""
    assert (
        publication_completeness({"source": "staatsblad", "kind": "publicatie"}) is None
    )
    assert publication_completeness({"source": "bwb", "kind": "wet"}) is None


def test_the_api_says_a_publication_has_its_text_not_fetched() -> None:
    found = completeness_dto({"source": "bwb", "kind": "publicatie"})
    assert found is not None
    assert {part.value: state.state.value for part, state in found.items()} == {
        "text": "not_fetched"
    }
