"""The pages on tweedekamer.nl follow from the numbers the site knows, per kind of node."""

from __future__ import annotations

import pytest

from lawgraph.core.tk_links import activity_page, document_page, tk_url

_COMMITTEE = (
    "https://www.tweedekamer.nl/debat_en_vergadering/commissievergaderingen/details?id="
)
_PLENARY = (
    "https://www.tweedekamer.nl/debat_en_vergadering/plenaire_vergaderingen/details/"
    "activiteit?id="
)


def test_a_document_page_is_found_by_its_document_number_twice() -> None:
    # id alone and did alone both answer 404; the GUID of the record is unknown to the site
    assert document_page("2026D44984") == (
        "https://www.tweedekamer.nl/kamerstukken/detail?id=2026D44984&did=2026D44984"
    )
    assert tk_url("document", {"document_number": "2026D44984"}) == document_page(
        "2026D44984"
    )


@pytest.mark.parametrize(
    "kind",
    [
        "Plenair debat (wetgeving)",
        "Plenair debat (tweeminutendebat)",
        "Plenair debat (dertigledendebat)",
        "Stemmingen",
        "Hamerstukken",
        "Regeling van werkzaamheden",
        "Vragenuur",
    ],
)
def test_a_plenary_activity_gets_the_plenary_page(kind: str) -> None:
    assert activity_page("2026A02881", kind) == _PLENARY + "2026A02881"


@pytest.mark.parametrize(
    "kind",
    [
        "Commissiedebat",
        "Procedurevergadering",
        "Hoorzitting",
        "Rondetafelgesprek",
        "Wetgevingsoverleg",
        "Notaoverleg",
        "Technische briefing",
        "E-mailprocedure",
        "Werkbezoek",
        None,
    ],
)
def test_any_other_activity_gets_the_committee_page(kind: str | None) -> None:
    assert activity_page("2026A02571", kind) == _COMMITTEE + "2026A02571"
    assert tk_url("activity", {"number": "2026A02571", "kind": kind}) == (
        _COMMITTEE + "2026A02571"
    )


def test_without_a_number_there_is_no_link_rather_than_a_dead_one() -> None:
    assert document_page(None) is None and document_page("") is None
    assert activity_page("", "Commissiedebat") is None
    # an Eerste Kamer paper has no document number: its own page is its url
    assert tk_url("document", {"source": "eerstekamer", "url": "https://x"}) is None
    assert tk_url("dossier", {"number": "37035"}) is None
    assert tk_url("decision", {"decision_id": "b1"}) is None
