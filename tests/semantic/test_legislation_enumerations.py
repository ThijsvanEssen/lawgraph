"""How legislation enumerates the articles of another law, each with its own parts: "de
artikelen 98, eerste en tweede lid, 98c, eerste lid, … van het Wetboek van Strafrecht". The
sentences are those of the new Wetboek van Strafvordering (Stb. 2026, 56). With ``chains``
the extractor reads such an enumeration as one citation; without it, as the running text of
a judgment, only its head."""

from __future__ import annotations

from lawgraph.core.citations import DutchCitationExtractor, parse_article_numbers

SR, AWB = "BWBR0001854", "BWBR0005537"
EXTRACTOR = DutchCitationExtractor(
    {"Sr": SR, "Awb": AWB},
    {"Wetboek van Strafrecht": SR, "Algemene wet bestuursrecht": AWB},
    as_written=True,
)
TEXT = (
    "dan wel een misdrijf als omschreven in de artikelen 98, eerste en tweede lid, 98c, "
    "eerste lid, 138ab, eerste tot en met derde lid, 138c, 139c, eerste lid, 160, 161, "
    "aanhef en onder 1°, 161sexies, aanhef en onder 1°, 350a, eerste tot en met derde lid, "
    "363, eerste en tweede lid en 420bis, eerste lid, van het Wetboek van Strafrecht."
)


def _cited(
    text: str, *, chains: bool
) -> list[tuple[str | None, str | None, str | None]]:
    return [
        (hit.bwb_id, hit.article_number, hit.qualifier)
        for hit in EXTRACTOR.extract(text, every_occurrence=True, chains=chains)
    ]


def test_an_enumeration_of_legislation_is_one_citation() -> None:
    assert _cited(TEXT, chains=True) == [
        (SR, "98", "eerste en tweede lid"),
        (SR, "98c", "eerste lid"),
        (SR, "138ab", "eerste tot en met derde lid"),
        (SR, "138c", None),
        (SR, "139c", "eerste lid"),
        (SR, "160", None),
        (SR, "161", "aanhef en onder 1°"),
        (SR, "161sexies", "aanhef en onder 1°"),
        (SR, "350a", "eerste tot en met derde lid"),
        (SR, "363", "eerste en tweede lid"),
        (SR, "420bis", "eerste lid"),
    ]


def test_without_chains_only_its_head() -> None:
    assert _cited(TEXT, chains=False) == []


def test_a_range_in_an_enumeration() -> None:
    text = "de artikelen 141, 157, 300 tot en met 303 of 350 van het Wetboek van Strafrecht"
    assert [n for _, n, _ in _cited(text, chains=True)] == [
        "141",
        "157",
        "300",
        "303",
        "350",
    ]


def test_the_parts_of_onderdelen_and_degrees() -> None:
    text = (
        "de artikelen 310 en 311, eerste lid, onderdelen 1°, 4° en 5°, van het Wetboek "
        "van Strafrecht"
    )
    assert _cited(text, chains=True) == [
        (SR, "310", None),
        (SR, "311", "eerste lid, onderdelen 1°, 4° en 5°"),
    ]


def test_a_head_alone_where_no_law_follows_the_enumeration() -> None:
    # the enumeration ends on words that name no law: the head is read as before
    text = "artikel 8:54 Awb, 3 weken"
    assert _cited(text, chains=True) == [(AWB, "8:54", None)]


def test_an_article_number_with_a_long_latin_ordinal() -> None:
    assert parse_article_numbers("161sexies, 420quater.1 en 420bis.1") == [
        "161sexies",
        "420quater.1",
        "420bis.1",
    ]
    assert _cited("artikel 161sexies Sr", chains=False) == [(SR, "161sexies", None)]
