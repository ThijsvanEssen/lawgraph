"""``AliasMatcher`` finds what one regex per label found, in one pass over the text."""

from __future__ import annotations

import re
import time

from lawgraph.core.aliases import AliasMatcher, code_aliases, curated_abbreviations

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
        # a pseudo instrument whose alias a law's short title claims as well
        {"bwb_id": "ECHR-CONVENTION", "aliases": ["EVRM", "X"]},
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
        "SR": "BWBR0001854",
        "WVS": "BWBR0001854",
        "WVSR": "BWBR0001854",
        "BW6": "BWBR0005289",
        "BW7": "BWBR0005290",
        "EVRM": "BWBV0001000",
        "ALGEMENE VERORDENING GEGEVENSBESCHERMING": "32016R0679",
        "AVG": "32016R0679",
    }


def test_the_curated_abbreviations_are_read_by_law_id() -> None:
    assert "AVG" in curated_abbreviations()["32016R0679"]
