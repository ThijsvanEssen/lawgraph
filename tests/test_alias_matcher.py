"""``AliasMatcher`` finds what one regex per label found, in one pass over the text."""

from __future__ import annotations

import re
import time

from lawgraph.core.aliases import (
    AliasMatcher,
    code_aliases,
    curated_abbreviations,
    instrument_names,
)

LABELS = [
    "Wegenwet",
    "Wet op de rechterlijke organisatie",
    "Wet",
    "wet op de Raad van State",
    "(EU) 2016/679",
    "Besluit omgevingsrecht",
    "Awb",
    "Wegenverkeerswet 1994",
]

TEXTS = [
    "De Wegenwet en de WEGENWET; ook de Wegenverkeerswet 1994, niet de Wegenverkeerswet 19945.",
    "Krachtens de wet op de rechterlijke organisatie (Wet RO) en de Wet op de Raad van State.",
    "Verordening (EU) 2016/679, x(EU) 2016/679 en (EU) 2016/6790.",
    "Grondwet, wetgeving, Wet. _Awb awb_ Awb, AWB",
    "",
    "Besluit omgevingsrecht",
    "İstanbul-Wet en de wet",
]


def _by_regex(labels: list[str], text: str) -> list[tuple[int, int, int]]:
    """The first match of each label with one compiled pattern per label."""
    found = []
    for order, label in enumerate(labels):
        match = re.search(rf"(?<!\w){re.escape(label)}(?!\w)", text, re.IGNORECASE)
        if match:
            found.append((order, *match.span()))
    return found


def test_matches_are_those_of_one_regex_per_label() -> None:
    matcher = AliasMatcher(LABELS)
    for text in TEXTS:
        assert matcher.first_matches(text) == _by_regex(LABELS, text), text


def test_a_name_inside_a_longer_word_does_not_match() -> None:
    assert AliasMatcher(["Wet"]).first_matches("Grondwet en wetgeving") == []


def test_cost_does_not_grow_with_the_number_of_labels() -> None:
    text = "De minister wijst op de Wegenwet en op artikel 5 van de Awb. " * 40
    few = AliasMatcher(LABELS)
    many = AliasMatcher(
        [*LABELS, *(f"Regeling nummer {n} van de minister" for n in range(20_000))]
    )

    def cost(matcher: AliasMatcher) -> float:
        started = time.perf_counter()
        for _ in range(20):
            matcher.first_matches(text)
        return time.perf_counter() - started

    assert many.first_matches(text) == few.first_matches(text)
    assert cost(many) < 5 * cost(few) + 0.05


# ── abbreviations ─────────────────────────────────────────────────────────────


def test_an_abbreviation_is_of_the_one_law_that_claims_it() -> None:
    rows = [
        {
            "bwb_id": "BWBR0001854",
            "short_title": "Sr",
            "aliases": ["Sr", "WvS", "WvSr"],
        },
        # every book of the BW lists BW; a digit starts the number of a citation
        {"bwb_id": "BWBR0005289", "short_title": "BW6", "aliases": ["BW", "6 BW"]},
        {"bwb_id": "BWBR0005290", "short_title": "BW7", "aliases": ["BW", "7 BW"]},
        # an instrument whose alias a law's short title claims as well
        {"bwb_id": "BWBV0009999", "aliases": ["EVRM", "X"]},
        {"bwb_id": "BWBV0001000", "short_title": "EVRM"},
        {"bwb_id": "BWBR0000001", "aliases": ["X"]},  # an alias two laws claim
        {
            "celex": "32016R0679",
            "short_title": "Algemene verordening gegevensbescherming",
        },
    ]

    # a curated abbreviation counts for a law in the graph only
    codes = code_aliases(rows, {"32016R0679": ["AVG"], "32000R0001": ["NIET"]})

    assert codes == {
        "Sr": "BWBR0001854",
        "WvS": "BWBR0001854",
        "WvSr": "BWBR0001854",
        "BW6": "BWBR0005289",
        "BW7": "BWBR0005290",
        "EVRM": "BWBV0001000",
        "Algemene verordening gegevensbescherming": "32016R0679",
        "AVG": "32016R0679",
    }


def test_an_abbreviation_of_the_source_wins_over_a_curated_one() -> None:
    rows = [
        {"bwb_id": "BWBR0000001", "aliases": ["ABC"]},
        {"celex": "32016R0679", "short_title": "Algemene verordening"},
    ]
    assert code_aliases(rows, {"32016R0679": ["ABC", "AVG"]}) == {
        "ABC": "BWBR0000001",
        "Algemene verordening": "32016R0679",
        "AVG": "32016R0679",
    }


def test_the_curated_abbreviations_are_read_by_law_id() -> None:
    assert "AVG" in curated_abbreviations()["32016R0679"]


RV = "Wetboek van Burgerlijke Rechtsvordering"


def test_a_variant_of_a_law_leaves_it_its_abbreviation() -> None:
    """Rv: the BWB gives the abbreviation to the code and to its version for procedures
    on paper, whose title is the code's with "(geldt …)" after it. The code keeps it; two
    laws that are no version of one another still share it with neither."""
    rows = [
        {"bwb_id": "BWBR0001827", "aliases": ["Rv"], "citation_title": RV},
        {
            "bwb_id": "BWBR0039872",
            "aliases": ["Rv"],
            "citation_title": f"{RV} (geldt in geval van niet-digitaal procederen)",
        },
        {"bwb_id": "BWBR0000001", "aliases": ["X"], "citation_title": "Wet een"},
        {"bwb_id": "BWBR0000002", "aliases": ["X"], "citation_title": "Wet twee"},
    ]
    assert code_aliases(rows) == {"Rv": "BWBR0001827"}


def test_a_title_with_its_year_is_also_cited_without_it() -> None:
    """ "Vreemdelingenwet" is the Vreemdelingenwet 2000 when no other law is called so or
    has that name with another year."""
    rows = [
        {"bwb_id": "BWBR0011823", "citation_title": "Vreemdelingenwet 2000"},
        {"bwb_id": "BWBR0006622", "citation_title": "Wegenverkeerswet 1994"},
        # two years of one name: neither is the name alone
        {"bwb_id": "BWBR0000003", "citation_title": "Wet voorbeeld 1990"},
        {"bwb_id": "BWBR0000004", "citation_title": "Wet voorbeeld 2005"},
        # a law that is called so itself keeps the name
        {"bwb_id": "BWBR0000005", "citation_title": "Mediawet 2008"},
        {"bwb_id": "BWBR0000006", "citation_title": "Mediawet"},
    ]
    names = instrument_names(rows)
    assert names["Vreemdelingenwet"] == ("BWBR0011823", None)
    assert names["Vreemdelingenwet 2000"] == ("BWBR0011823", None)
    assert names["Wegenverkeerswet"] == ("BWBR0006622", None)
    assert "Wet voorbeeld" not in names
    assert names["Mediawet"] == ("BWBR0000006", None)


def test_an_earlier_citation_title_names_its_law_after_every_current_one() -> None:
    rows = [
        {
            "bwb_id": "BWBR0015703",
            "citation_title": "Participatiewet",
            "citation_titles": ["Participatiewet", "Wet werk en bijstand"],
        },
        # an earlier title that is another law's title now names that law
        {
            "bwb_id": "BWBR0035362",
            "citation_title": "Wet maatschappelijke ondersteuning 2015",
            "citation_titles": ["Wet maatschappelijke ondersteuning"],
        },
        {
            "bwb_id": "BWBR0020031",
            "citation_title": "Wet maatschappelijke ondersteuning",
        },
        # an earlier title two laws had names neither
        {"bwb_id": "BWBR0000001", "citation_titles": ["Oude wet"]},
        {"bwb_id": "BWBR0000002", "citation_titles": ["Oude wet"]},
    ]
    names = instrument_names(rows)
    assert names["Wet werk en bijstand"] == ("BWBR0015703", None)
    assert names["Wet maatschappelijke ondersteuning"] == ("BWBR0020031", None)
    assert "Oude wet" not in names
