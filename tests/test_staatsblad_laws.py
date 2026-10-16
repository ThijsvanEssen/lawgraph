"""A law of the Staatsblad the BWB does not hold, read from its publication: excerpts of the
XML of Stb. 2026, 56 (the Wetboek van Strafvordering) and Stb. 2026, 57 (the Tweede
vaststellingswet, which gives Boek 1, Hoofdstuk 10 and Boek 7 their text)."""

from __future__ import annotations

from pathlib import Path

import pytest

from lawgraph.core.staatsblad_laws import (
    LawPublication,
    article_props,
    law_props,
    law_text,
    own_references,
    read_publication,
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
        "1.10.1",
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
