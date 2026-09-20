"""Parsing real BWB toestand XML (recorded fixtures)."""

from __future__ import annotations

import pathlib

import pytest

from lawgraph.core.bwb_xml import (
    EFFECT_AMENDS,
    EFFECT_INTRODUCES,
    EFFECT_REPEALS,
    effect_kind,
    parse_jci,
    parse_toestand,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def grondwet():
    return parse_toestand((FIXTURES / "bwb_grondwet_toestand.xml").read_text())


@pytest.fixture(scope="module")
def amvb():
    return parse_toestand((FIXTURES / "bwb_amvb_toestand.xml").read_text())


def _by_path(toestand, path):
    return next(a for a in toestand.articles if a.path == path)


def test_instrument_metadata(grondwet) -> None:
    assert grondwet.bwb_id == "BWBR0001840"
    assert grondwet.kind == "wet"
    assert grondwet.citation_title == "Grondwet"
    assert grondwet.official_title.startswith("Grondwet voor het Koninkrijk")
    assert grondwet.title == "Grondwet"  # citation title wins, as before
    assert grondwet.valid_from == "2022-07-06"


def test_instrument_level_publication_carries_the_dossier(grondwet) -> None:
    assert grondwet.origin.identifier == "stb-2022-332"
    assert grondwet.origin.dossiers == ("35786",)
    assert grondwet.origin.signed == "2022-07-06"


def test_article_identity_and_version_fields(grondwet) -> None:
    art7 = _by_path(grondwet, "/Hoofdstuk1/Artikel7")

    assert art7.number == "7"
    assert (art7.stam_id, art7.versie_id) == ("2990103", "25689252")
    assert art7.valid_from == "2018-12-21"
    assert art7.source == "Stb.2019-33"
    assert art7.effect == "tekstplaatsing-wijziging"
    assert effect_kind(art7.effect) == EFFECT_AMENDS


def test_article_documents_and_their_dossiers(grondwet) -> None:
    art7 = _by_path(grondwet, "/Hoofdstuk1/Artikel7")

    assert art7.origin.identifier == "stb-2019-33"
    assert (art7.origin.kind, art7.origin.year, art7.origin.number) == (
        "Stb",
        2019,
        "33",
    )
    assert art7.origin.published == "2019-02-08"
    assert art7.commencement.identifier == "stb-2018-493"
    assert art7.commencement.dossiers == ("34716",)  # the dossier sits on this one


def test_article_text_keeps_lid_numbers_and_all_leden(grondwet) -> None:
    art7 = _by_path(grondwet, "/Hoofdstuk1/Artikel7")

    lines = art7.text.split("\n")
    assert [line[:2] for line in lines] == ["1.", "2.", "3.", "4."]
    assert lines[0].startswith("1. Niemand heeft voorafgaand verlof nodig")


def test_repealed_and_new_articles(grondwet) -> None:
    repealed = _by_path(grondwet, "/Hoofdstuk5/Paragraaf2/Artikel101")
    new = next(a for a in grondwet.articles if a.effect == "nieuw")

    assert repealed.is_repealed and repealed.text == "Vervallen"
    assert effect_kind(new.effect) == EFFECT_INTRODUCES
    assert effect_kind("vervallen") == EFFECT_REPEALS
    assert effect_kind("iets-nieuws") is None


def test_references_have_offsets_that_match_the_text(grondwet) -> None:
    refs = [r for a in grondwet.articles for r in a.references]
    assert refs, "fixture should contain intref/extref"
    for article in grondwet.articles:
        for ref in article.references:
            assert article.text[ref.start : ref.end] == ref.text
            assert ref.bwb_id


def test_internal_reference_resolves_to_a_target_article(grondwet) -> None:
    art92 = _by_path(grondwet, "/Hoofdstuk5/Paragraaf2/Artikel92")

    (ref,) = art92.references
    assert (ref.kind, ref.bwb_id, ref.article) == ("intref", "BWBR0001840", "91")
    assert ref.text == "artikel 91, derde lid"


def test_references_without_an_article_number_are_kept_but_have_no_article(
    grondwet,
) -> None:
    art82 = _by_path(grondwet, "/Hoofdstuk5/Paragraaf1/Artikel82")

    assert [r.article for r in art82.references] == [None]  # a reference to a chapter


def test_external_reference_targets_another_regulation(grondwet) -> None:
    art142 = _by_path(grondwet, "/Hoofdstuk8/Artikel142")

    external = [r for r in art142.references if r.kind == "extref"]
    assert external and all(r.bwb_id != "BWBR0001840" for r in external)
    assert [r.article for r in art142.references if r.kind == "intref"] == [
        "139",
        "140",
        "141",
    ]


def test_legal_basis_comes_from_the_preamble(amvb) -> None:
    basis = {(b.bwb_id, b.article) for b in amvb.basis}

    assert ("BWBR0001947", "125") in basis
    assert ("BWBR0001947", "133") in basis
    assert all(b.bwb_id != amvb.bwb_id for b in amvb.basis)


def test_preamble_references_that_are_not_the_legal_basis_are_ignored(amvb) -> None:
    # "Op de voordracht…" and "Den Raad van State gehoord" paragraphs carry no basis
    assert len(amvb.basis) <= 6


@pytest.mark.parametrize(
    ("doc", "bwb_id", "article"),
    [
        (
            "jci1.3:c:BWBR0001854&hoofdstuk=1&artikel=287&z=2023-01-01",
            "BWBR0001854",
            "287",
        ),
        ("jci1.3:c:BWBR0002154", "BWBR0002154", None),
        ("jci1.3:c:BWBV0001000&artikel=3a", "BWBV0001000", "3a"),
        ("kst-35165-25", None, None),
        (None, None, None),
    ],
)
def test_parse_jci(doc, bwb_id, article) -> None:
    jci = parse_jci(doc)
    assert (jci.bwb_id, jci.article) == (bwb_id, article)


def _collapse(text: str) -> str:
    return " ".join(text.split())


def _paragraphs(element):
    """Every <al> under *element*, skipping metadata (editorial remarks are not law text)."""
    from lawgraph.core.xml import local_name

    for child in element:
        name = local_name(child.tag)
        if name == "meta-data":
            continue
        if name == "al":
            yield child
        yield from _paragraphs(child)


@pytest.mark.parametrize(
    "fixture", ["bwb_grondwet_toestand.xml", "bwb_amvb_toestand.xml"]
)
def test_no_paragraph_text_is_lost(fixture: str) -> None:
    """Every law-text <al> of every article ends up in the article text (fidelity check)."""
    import xml.etree.ElementTree as ET

    from lawgraph.core.xml import local_name

    xml = (FIXTURES / fixture).read_text()
    parsed = parse_toestand(xml)
    by_path = {a.path: a for a in parsed.articles}

    checked = 0
    for element in ET.fromstring(xml).iter():
        if local_name(element.tag) != "artikel":
            continue
        flat = _collapse(by_path[element.get("bwb-ng-variabel-deel")].text)
        for al in _paragraphs(element):
            paragraph = _collapse("".join(al.itertext()))
            if paragraph:
                assert paragraph in flat, (
                    f"{element.get('bwb-ng-variabel-deel')}: lost {paragraph[:60]!r}"
                )
                checked += 1
    assert checked > 0


def test_list_items_are_kept_on_their_own_lines(grondwet) -> None:
    art138 = _by_path(grondwet, "/Hoofdstuk8/Artikel138")

    assert "\na. de aangenomen voorstellen" in art138.text
    assert "\nb. de indeling in en de plaats" in art138.text


def test_a_paragraph_next_to_the_leden_is_part_of_the_article() -> None:
    """Real case: a 'not yet in force' note sits beside the leden, before them in the source."""
    parsed = parse_toestand((FIXTURES / "bwb_wet_not_in_force.xml").read_text())

    art5 = next(a for a in parsed.articles if a.path == "/Paragraaf1/Artikel5")

    assert "Dit artikel is nog niet in werking getreden" in art5.text
    # document order: the note precedes the first lid
    assert art5.text.index("Dit artikel is nog niet") < art5.text.index(
        "\n1. Onze Minister"
    )
