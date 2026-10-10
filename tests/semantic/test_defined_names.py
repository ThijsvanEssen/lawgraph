"""A judgment names a law in full and gives it an abbreviation ("de Werkloosheidswet (WW)"),
also where the abbreviation stands for several laws in the registry: in that text it is the
law it named."""

from __future__ import annotations

from lawgraph.core.citations import DutchCitationExtractor

WW = "BWBR0004045"
WONINGWET = "BWBR0005181"
PW = "BWBR0015703"
NAMES = {
    "Werkloosheidswet": WW,
    "Woningwet": WONINGWET,
    "Participatiewet": PW,
    "Wet werk en bijstand": PW,
}


def _hits(
    text: str, codes: dict[str, str] | None = None
) -> list[tuple[str | None, str]]:
    extractor = DutchCitationExtractor(code_aliases=codes or {}, name_aliases=NAMES)
    return [(h.bwb_id, h.article_number) for h in extractor.extract(text)]


def test_a_name_and_its_abbreviation_outside_a_citation() -> None:
    text = (
        "Appellant ontving een uitkering op grond van de Werkloosheidswet (WW). "
        "Op grond van artikel 17, eerste lid, van de WW ontstaat recht op een uitkering."
    )
    assert _hits(text) == [(WW, "17")]


def test_hierna_and_an_old_title() -> None:
    text = (
        "Bijstand op grond van de Wet werk en bijstand (hierna: WWB) is toegekend. "
        "Ingevolge artikel 54, eerste lid, van de WWB verstrekt het college inlichtingen."
    )
    assert _hits(text) == [(PW, "54")]


def test_a_definition_holds_in_the_whole_text() -> None:
    # the citation stands before the definition in the text, and in another paragraph
    text = (
        "Artikel 13 van de Pw is van toepassing.\n\nDe Participatiewet (Pw) regelt de "
        "bijstand."
    )
    assert _hits(text) == [(PW, "13")]


def test_an_abbreviation_the_text_does_not_define_names_no_law() -> None:
    assert _hits("artikel 17 van de WW is van toepassing.") == []


def test_a_code_of_the_registry_keeps_its_law() -> None:
    text = "de Woningwet (Wvw) en artikel 5 van de Wvw"
    assert _hits(text, {"Wvw": "BWBR0006622"}) == [("BWBR0006622", "5")]


def test_a_parenthesis_after_no_law_name_defines_nothing() -> None:
    text = (
        "Het Uitvoeringsinstituut werknemersverzekeringen (WW) en artikel 17 van de WW."
    )
    assert _hits(text) == []
