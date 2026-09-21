"""The forms in which judgments cite articles, taken from real judgments.

Each sentence below was found in a judgment downloaded from the Rechtspraak; a citation the
detector did not recognise is what these tests are for.
"""

from __future__ import annotations

import pytest

from lawgraph.core.citations import DutchCitationExtractor

SR, SV, RV, FW = "BWBR0001854", "BWBR0001903", "BWBR0001827", "BWBR0001860"
AWB, WRO, WABO, OPIUM = "BWBR0005537", "BWBR0002375", "BWBR0024779", "BWBR0001941"
WVW, VW2000, OMGEVING = "BWBR0006622", "BWBR0011823", "BWBR0037885"
BW6, BW1 = "BWBR0005289", "BWBR0002656"

CODES = {
    "Sr": SR,
    "Sv": SV,
    "Rv": RV,
    "Fw": FW,
    "Awb": AWB,
    "BW1": BW1,
    "BW6": BW6,
    "Wet WOZ": "BWBR0007399",
}
NAMES = {
    "Algemene wet bestuursrecht": AWB,
    "Wetboek van Strafvordering": SV,
    "Opiumwet": OPIUM,
    "Wegenverkeerswet 1994": WVW,
    "Omgevingswet": OMGEVING,
    "Wet ruimtelijke ordening": WRO,
    "Wet algemene bepalingen omgevingsrecht": WABO,
    "Vreemdelingenwet 2000": VW2000,
}


def _found(text: str, codes=CODES, names=NAMES) -> list[tuple[str, str | None, float]]:
    hits = DutchCitationExtractor(code_aliases=codes, name_aliases=names).extract(text)
    return [(h.bwb_id, h.article_number, h.confidence) for h in hits]


def _ids(text: str, codes=CODES, names=NAMES) -> list[tuple[str, str | None]]:
    return [(law, number) for law, number, _ in _found(text, codes, names)]


# ── how the article is qualified ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("art. 1:88 lid 5 BW respectievelijk", [(BW1, "88")]),
        (
            "artikel 359 derde lid van het Wetboek van Strafvordering (Sv)",
            [(SV, "359")],
        ),
        ("artikel 359a, tweede lid, Sv", [(SV, "359a")]),
        ("artikel 10, tweede lid, aanhef en onder a, Sr", [(SR, "10")]),
        ("artikel 3 onder c Opiumwet", [(OPIUM, "3")]),
        ("artikel 2, eerste lid, onderdeel b, Awb", [(AWB, "2")]),
        (
            "artikel 126aa, tweede lid, eerste volzin, van het Wetboek van Strafvordering",
            [(SV, "126aa")],
        ),
        ("artikel 8:29 lid 1 en 2 Awb", [(AWB, "8:29")]),
    ],
)
def test_the_lid_and_the_parts_of_an_article(text, expected) -> None:
    assert _ids(text) == expected


def test_the_qualifier_is_kept() -> None:
    hits = DutchCitationExtractor(code_aliases=CODES).extract(
        "artikel 10, tweede lid, Sr"
    )
    assert hits[0].qualifier == "tweede lid"


# ── the number of the article ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("artikel 3.26, eerste lid, van de Wet ruimtelijke ordening", [(WRO, "3.26")]),
        (
            "artikel 3.9, derde lid, eerste zin, van de Wet algemene bepalingen omgevingsrecht",
            [(WABO, "3.9")],
        ),
        (
            "artikel 5.1, eerste lid, aanhef en onder a, van de Omgevingswet",
            [(OMGEVING, "5.1")],
        ),
        (
            "artikel 1.1a sub 1 van de Wet algemene bepalingen omgevingsrecht",
            [(WABO, "1.1a")],
        ),
        (
            "artikel 8:54, eerste lid, van de Algemene wet bestuursrecht",
            [(AWB, "8:54")],
        ),
        ("art. 137c Sr", [(SR, "137c")]),
        ("artikel 420bis Sr", [(SR, "420bis")]),
        ("art 12 Sv", [(SV, "12")]),
    ],
)
def test_the_forms_of_an_article_number(text, expected) -> None:
    assert _ids(text) == expected


def test_a_sentence_ending_dot_is_not_part_of_the_number() -> None:
    assert _ids("Het gaat om artikel 137c. Sr is niet van toepassing.") == []
    assert _ids("Het gaat om artikel 137c Sr.") == [(SR, "137c")]


# ── which law: code or full name ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("artikel 10 van de Opiumwet door", [(OPIUM, "10")]),
        ("artikel 8 van de Wegenverkeerswet 1994 (hierna: WVW1994) en", [(WVW, "8")]),
        (
            "artikel 72, derde lid, van de Vreemdelingenwet 2000 als hij",
            [(VW2000, "72")],
        ),
        ("artikel 40 Wet WOZ om alle op de zaak betrekking", [("BWBR0007399", "40")]),
        ("artikel 4 Opiumwet, dan wel", [(OPIUM, "4")]),
        ("ARTIKEL 4 OPIUMWET", [(OPIUM, "4")]),
    ],
)
def test_the_law_is_named_by_code_or_by_full_name(text, expected) -> None:
    assert _ids(text) == expected


def test_the_longest_known_name_wins() -> None:
    names = {"Wet op de rechterlijke organisatie": "BWBR0001827", "Wet": "BWBR0001854"}
    assert _ids(
        "artikel 81 van de Wet op de rechterlijke organisatie zegt", {}, names
    ) == [("BWBR0001827", "81")]


def test_a_name_that_is_not_a_law_is_not_a_hit() -> None:
    assert _ids("artikel 15 van de algemene huurvoorwaarden een boete") == []
    assert _ids("artikel 1.50 van het bestemmingsplan Giethoorn") == []
    assert _ids("artikel 33 van de Verordening ruimte een afweging") == []


def test_very_many_names_cost_no_regex_alternation() -> None:
    names = {f"Wet nummer {n}": f"BWBR{n:07d}" for n in range(30_000)}
    text = "artikel 5 van de Wet nummer 29999 is van toepassing"
    assert _ids(text, {}, names) == [("BWBR0029999", "5")]


# ── enumerations ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("artikelen 338 (lid 2) en 339 Fw jo", [(FW, "338"), (FW, "339")]),
        ("art. 218 (of 218a) Sv op een verschoningsrecht", [(SV, "218")]),
        ("artikelen 22, 27 en 63 Sr", [(SR, "22"), (SR, "27"), (SR, "63")]),
        ("artikelen 2 tot en met 5 Sv", [(SV, "2"), (SV, "5")]),
        ("de artikelen 94 en 96b Sv", [(SV, "94"), (SV, "96b")]),
    ],
)
def test_enumerations_with_parentheses_and_ranges(text, expected) -> None:
    assert _ids(text) == expected


# ── book families and the alias a text gives ─────────────────────────────────


def test_a_family_code_still_resolves_through_the_book() -> None:
    assert _ids("art. 6:162 BW en artikel 1:88 BW") == [(BW6, "162"), (BW1, "88")]


def test_a_name_the_text_defines_is_used_further_on() -> None:
    """Judgments write the law out once and name it (hierna: ...) for the rest."""
    text = (
        "artikel 8:29 van de Algemene wet bestuursrecht (hierna: de Wnb) ten aanzien van "
        "stukken. Volgens artikel 2.8, derde lid, van de Wnb is het verboden."
    )
    assert _ids(text) == [(AWB, "8:29"), (AWB, "2.8")]
    assert [c for _, _, c in _found(text)] == [0.95, 0.9]


def test_a_hierna_alias_is_local_to_the_text() -> None:
    extractor = DutchCitationExtractor(code_aliases=CODES, name_aliases=NAMES)
    extractor.extract(
        "artikel 8:29 van de Algemene wet bestuursrecht (hierna: de Wnb) en"
    )
    assert extractor.extract("artikel 2.8 van de Wnb") == []


def test_a_hierna_alias_does_not_replace_a_registered_code() -> None:
    text = "artikel 1 van het Wetboek van Strafvordering (hierna: Sr) en artikel 2 Sr."
    assert _ids(text) == [(SV, "1"), (SR, "2")]


# ── "van die wet" ────────────────────────────────────────────────────────────


def test_die_wet_is_the_law_named_last() -> None:
    text = "artikel 8:54 van de Algemene wet bestuursrecht en artikel 3a van die wet"
    assert _found(text) == [(AWB, "8:54", 0.95), (AWB, "3a", 0.7)]


def test_die_wet_without_a_law_before_it_is_nothing() -> None:
    assert _ids("artikel 3a van die wet") == []


def test_die_wet_does_not_reach_far_back() -> None:
    text = (
        "artikel 8:54 van de Algemene wet bestuursrecht"
        + " x" * 3000
        + " artikel 3a van die wet"
    )
    assert _ids(text) == [(AWB, "8:54")]


@pytest.mark.parametrize("word", ["deze", "dezelfde", "genoemde", "voornoemde"])
def test_the_ways_to_point_back(word) -> None:
    text = f"artikel 1 Sr. Verder artikel 2 van {word} wet"
    assert (SR, "2") in _ids(text)


# ── nothing to link ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "artikel 14 doorgehaald, artikel 17",
        "Artikel 2. Aard van de belasting Onder de naam rioolheffing",
        "artikel 38 lid 10 wordt nageleefd",
        "artikel 1 van de huurovereenkomst onlosmakelijk onderdeel uitmaakt",
        "",
    ],
)
def test_internal_references_and_unknown_documents_are_not_hits(text) -> None:
    assert _ids(text) == []


def test_without_any_law_registered_nothing_is_found() -> None:
    assert DutchCitationExtractor(code_aliases={}).extract("artikel 5 Sr") == []
