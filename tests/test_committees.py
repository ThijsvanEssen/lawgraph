"""A committee's kind, and a slug of its own for committees that share an abbreviation."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.core.tk_records import committee_kind, unique_committee_slugs


@pytest.mark.parametrize(
    ("name", "group", "kind"),
    [
        ("Vaste commissie voor Economische Zaken", None, "vast"),
        (
            "Algemene commissie voor Buitenlandse Handel en Ontwikkelingssamenwerking",
            None,
            "algemeen",
        ),
        ("Tijdelijke commissie Digitale toekomst", None, "tijdelijk"),
        ("Themacommissie Ouderenbeleid", None, "tijdelijk"),
        ("Parlementaire enquêtecommissie Fyra", "Tijdelijke commissies", "enquete"),
        ("Parlementaire ondervragingscommissie Kinderopvangtoeslag", None, "enquete"),
        ("Enquêtecommissie Srebrenica", None, "enquete"),
        ("Commissie Vernieuwing Wet op de Parlementaire Enquête", None, "overig"),
        ("Contactgroep Duitsland", None, "delegatie"),
        ("IPC Cosac", None, "delegatie"),
        ("NAVO Parlementaire Assemblee", None, "delegatie"),
        ("Commissie voor de Rijksuitgaven", "Algemene commissies", "algemeen"),
        ("Bouwbegeleidingscommissie", "Tijdelijke commissies", "tijdelijk"),
        ("Presidium", "Overige commissies", "overig"),
    ],
)
def test_the_kind_of_a_committee(name: str, group: str | None, kind: str) -> None:
    assert committee_kind(name, group) == kind


def _committee(
    external_id: str, started: str | None, ended: str | None
) -> dict[str, Any]:
    return {
        "external_id": external_id,
        "slug": "ez",
        "started_on": started,
        "ended_on": ended,
    }


def test_the_sitting_committee_keeps_the_slug_and_the_others_get_a_year() -> None:
    old = _committee("a", "2010-10-14", "2017-10-26")
    sitting = _committee("b", "2024-07-02", None)
    older = _committee("c", "2002-05-23", "2003-01-30")
    same_year = _committee("d", "2010-02-01", "2010-10-14")
    unknown = _committee("e", None, None)
    unique_committee_slugs([old, sitting, older, same_year, unknown])

    assert sitting["slug"] == "ez"
    assert (old["slug"], older["slug"], same_year["slug"]) == (
        "ez-2010",
        "ez-2002",
        "ez-2010-2",
    )
    assert unknown["slug"] not in {"ez", "ez-2010", "ez-2002", "ez-2010-2"}
