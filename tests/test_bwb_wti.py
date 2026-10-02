"""WTI parsing and the short-title rule, on real ``<algemene-informatie>`` XML."""

from __future__ import annotations

import json
import pathlib
import xml.etree.ElementTree as ET

import pytest

from lawgraph.core.bwb_wti import (
    assign_slugs,
    choose_short_titles,
    extract_general_info,
    instrument_aliases,
    label_concepts,
    parse_abbreviations,
    parse_subjects,
    thesaurus_concepts,
    with_concepts,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
# The first bytes of the Wetboek van Strafrecht WTI, cut off inside the next element.
SR_HEAD = (FIXTURES / "bwb_wti_sr_head.xml").read_text()
# The element as it is stored, of Burgerlijk Wetboek Boek 1.
BW1_GENERAL = (FIXTURES / "bwb_wti_bw1_general.xml").read_text()


def test_extracts_the_complete_element_from_a_truncated_file() -> None:
    general_info = extract_general_info(SR_HEAD)

    assert general_info is not None
    assert general_info.startswith("<algemene-informatie ")
    assert general_info.endswith("</algemene-informatie>")
    ET.fromstring(general_info)  # well-formed on its own


def test_an_incomplete_or_missing_element_yields_nothing() -> None:
    cut = SR_HEAD[: SR_HEAD.index("</algemene-informatie>")]

    assert extract_general_info(cut) is None
    assert extract_general_info("<wetstechnische-informatie/>") is None


def test_abbreviations_come_in_source_order() -> None:
    general_info = extract_general_info(SR_HEAD)
    assert general_info is not None

    assert parse_abbreviations(general_info) == ["Sr", "WvS", "WvSr"]
    assert parse_abbreviations(BW1_GENERAL) == ["BW", "BW Boek 1", "BW1"]


def test_case_variants_count_once_and_absence_is_an_empty_list() -> None:
    variant = BW1_GENERAL.replace("BW Boek 1", "bw").replace(">BW1<", "> <")
    without = BW1_GENERAL.replace("afkorting", "x")

    assert parse_abbreviations(variant) == ["BW"]
    assert parse_abbreviations(without) == []


def test_of_two_spellings_the_one_a_citation_writes_is_kept() -> None:
    # the Grondwet: the source lists "GW" and "Gw", sorted, capitals first
    grondwet = BW1_GENERAL.replace(">BW<", ">GW<").replace(">BW Boek 1<", ">Gw<")
    grondwet = grondwet.replace(">BW1<", ">GW<")

    assert parse_abbreviations(grondwet) == ["Gw"]
    assert choose_short_titles({"BWBR0001840": parse_abbreviations(grondwet)}) == {
        "BWBR0001840": "Gw"
    }


def test_broken_xml_raises() -> None:
    with pytest.raises(ET.ParseError):
        parse_abbreviations("<algemene-informatie>")


def test_the_shortest_abbreviation_wins() -> None:
    chosen = choose_short_titles(
        {
            "BWBR0001854": ["Sr", "WvS", "WvSr"],
            "BWBR0006622": ["WVW", "WVW 1994"],
            "BWBR0005537": ["Awb"],
            "BWBR0040179": [],
        }
    )

    assert chosen == {
        "BWBR0001854": "Sr",
        "BWBR0006622": "WVW",
        "BWBR0005537": "Awb",
        "BWBR0040179": None,
    }


def test_equal_lengths_keep_the_source_order() -> None:
    assert choose_short_titles({"X": ["Wft", "Wfm"]}) == {"X": "Wft"}


def test_an_abbreviation_claimed_by_several_regulations_never_wins() -> None:
    chosen = choose_short_titles(
        {
            "BWBR0002656": ["BW", "BW Boek 1", "BW1"],
            "BWBR0005288": ["bw", "BW Boek 5", "BW5"],
            "BWBR0000001": ["BW"],
        }
    )

    assert chosen == {
        "BWBR0002656": "BW1",
        "BWBR0005288": "BW5",
        "BWBR0000001": None,
    }


def test_case_variants_of_one_regulation_are_one_claim() -> None:
    assert choose_short_titles({"BWBR0001840": ["GW", "Gw"]}) == {"BWBR0001840": "Gw"}


def test_a_code_of_books_never_wins_even_when_one_book_is_loaded() -> None:
    # Only Boek 7 loaded: "BW" is claimed once, but it names every book.
    assert choose_short_titles({"BWBR0005290": ["BW", "BW Boek 7", "BW7"]}) == {
        "BWBR0005290": "BW7"
    }


def test_every_book_of_a_code_is_named_by_the_code_and_every_form_of_its_number() -> (
    None
):
    aliases = instrument_aliases(
        {"BWBR0005289": ["BW", "BW Boek 6", "BW6"], "BWBR0001854": ["Sr", "WvS"]}
    )
    assert aliases["BWBR0005289"] == [
        "BW",
        "BW Boek 6",
        "BW6",
        "Boek 6 BW",
        "6 BW",
        "BW 6",
    ]
    assert aliases["BWBR0001854"] == ["Sr", "WvS"]
    # a book without a WTI record still has the forms of its code
    assert aliases["BWBR0002656"] == [
        "Boek 1 BW",
        "1 BW",
        "BW 1",
        "BW1",
        "BW Boek 1",
        "BW",
    ]


def test_aliases_that_differ_in_case_only_are_one() -> None:
    assert instrument_aliases({"BWBR0001840": ["GW", "Gw"]})["BWBR0001840"] == ["GW"]


# ── legal areas and government themes ────────────────────────────────────────

LEGAL_AREAS = thesaurus_concepts(
    json.loads((FIXTURES / "tooi_bwb_rechtsgebieden.json").read_text())
)  # TOOI scw_bwb_rechtsgebieden, version 2
THEMES = thesaurus_concepts(
    json.loads((FIXTURES / "tooi_bwb_themas.json").read_text())
)  # TOOI scw_bwb_themas, version 2


def test_the_legal_areas_and_themes_of_a_regulation() -> None:
    areas, domains = parse_subjects(BW1_GENERAL)

    assert areas == [
        {"main": "Personen- en familierecht", "specific": "Familierecht"},
        {"main": "Personen- en familierecht", "specific": "Personenrecht"},
    ]
    assert domains == ["Familie, jeugd en gezin"]


def test_each_label_has_its_tooi_concept() -> None:
    assert len(LEGAL_AREAS) == 104 and len(THEMES) == 21
    areas, domains = with_concepts(*parse_subjects(BW1_GENERAL), LEGAL_AREAS, THEMES)

    assert areas[0] == {
        "main": "Personen- en familierecht",
        "main_id": "c_5d8350bb",
        "main_uri": "https://identifier.overheid.nl/tooi/def/thes/bwb/c_5d8350bb",
        "main_slug": "personen-en-familierecht",
        "specific": "Familierecht",
        "specific_id": "c_e49bce03",
        "specific_uri": "https://identifier.overheid.nl/tooi/def/thes/bwb/c_e49bce03",
        "specific_slug": "familierecht",
    }
    assert domains[0]["label"] == "Familie, jeugd en gezin"
    assert domains[0]["uri"].startswith(
        "https://identifier.overheid.nl/tooi/def/thes/bwb/"
    )


def test_a_label_the_thesaurus_lacks_has_no_uri_and_a_repeat_is_kept_once() -> None:
    general = (
        "<algemene-informatie><rechtsgebieden>"
        "<rechtsgebied><hoofdgebied>Nieuw recht</hoofdgebied></rechtsgebied>"
        "<rechtsgebied><hoofdgebied>Nieuw recht</hoofdgebied></rechtsgebied>"
        "</rechtsgebieden><overheidsdomeinen><overheidsdomein>Belastingen</overheidsdomein>"
        "<overheidsdomein>Belastingen</overheidsdomein></overheidsdomeinen>"
        "</algemene-informatie>"
    )
    areas, domains = with_concepts(*parse_subjects(general), LEGAL_AREAS, THEMES)

    assert areas == [
        {
            "main": "Nieuw recht",
            "main_id": None,
            "main_uri": None,
            "main_slug": None,
            "specific": None,
            "specific_id": None,
            "specific_uri": None,
            "specific_slug": None,
        }
    ]
    assert len(domains) == 1 and domains[0]["uri"] is not None  # "belastingen"
    assert parse_subjects("<algemene-informatie/>") == ([], [])


def test_every_slug_of_a_thesaurus_is_unique() -> None:
    for concepts in (LEGAL_AREAS, THEMES):
        slugs = [c["slug"] for c in concepts.values()]
        assert len(slugs) == len(set(slugs))
    assert (
        THEMES["overheid, bestuur en koninkrijk"]["slug"]
        == "overheid-bestuur-en-koninkrijk"
    )


def test_a_slug_that_is_taken_gets_its_broader_concept_in_front() -> None:
    slugs = assign_slugs(
        [
            ("b", "Bestuursrecht", None),
            ("s", "Strafrecht", None),
            ("b1", "Algemeen", "b"),
            ("s1", "Algemeen", "s"),
            ("x", "Algemeen", None),
            ("e", "Één én ander", None),
        ]
    )
    assert slugs == {
        "b": "bestuursrecht",
        "e": "een-en-ander",
        "s": "strafrecht",
        "x": "algemeen",
        "b1": "bestuursrecht-algemeen",
        "s1": "strafrecht-algemeen",
    }


def test_without_the_thesaurus_the_labels_make_the_concepts() -> None:
    concepts = label_concepts(
        [("Bestuursrecht", None), ("Algemeen", "Bestuursrecht"), ("Algemeen", None)]
    )
    assert concepts["algemeen"] == {"id": None, "uri": None, "slug": "algemeen"}
    assert concepts["bestuursrecht"]["slug"] == "bestuursrecht"
