"""National implementing measures of EUR-Lex: the publication a measure is, and the measures
of a page of CELLAR rows (rows as CELLAR answered them)."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.clients.eu import _measures, _measures_sparql
from lawgraph.core.eurlex_nim import measure_publication

STB = "Staatsblad (Bulletin des Lois et des Décrets royaux)"
STCRT = "Staatscourant (Journal Officiel néerlandais)"


@pytest.mark.parametrize(
    ("measure", "publication"),
    [
        ({"journal": STB, "number": "401", "date": "2018-11-12"}, "stb-2018-401"),
        (
            {"journal": STCRT, "number": "20853", "date": "2026-06-10"},
            "stcrt-2026-20853",
        ),
        ({"journal": STB, "number": "178/2002", "date": "2002-03-15"}, "stb-2002-178"),
        ({"journal": STB, "number": "2005/24", "date": "2005-02-03"}, "stb-2005-24"),
        ({"number": "stb-2025-449", "date": "1001-01-01"}, "stb-2025-449"),
        (
            {
                "journal": STB,
                "number": "329",
                "title": "Koninklijk Besluit tot wijziging, Staatsblad 1992, nr. 329",
            },
            "stb-1992-329",
        ),
        (
            {
                "journal": STB,
                "number": "603",
                "title": "Staatsblad nummer 603 van 1997",
            },
            "stb-1997-603",
        ),
        ({"journal": STB, "number": "2025, 449", "date": "2025-12-23"}, "stb-2025-449"),
        # no journal: a wet is in the Staatsblad, a ministeriele regeling in the Staatscourant
        ({"number": "153", "date": "2026-06-24", "type": "Wet"}, "stb-2026-153"),
        (
            {"number": "20853", "date": "2026-06-10", "type": "Ministeriele regeling"},
            "stcrt-2026-20853",
        ),
        ({"number": "128", "date": "2026-06-10", "type": "Besluit"}, None),
        # no journal of ours, a placeholder date, numbers that do not fit the year
        ({"journal": "Administrative measures", "number": "17708"}, None),
        ({"journal": STB, "number": "600", "date": "1001-01-01"}, None),
        ({"journal": STB, "number": "2005/711", "date": "2004-12-13"}, None),
        ({"journal": STB, "number": "329", "title": "Staatsblad 1992, nr. 330"}, None),
    ],
)
def test_the_publication_a_measure_is(
    measure: dict[str, Any], publication: str | None
) -> None:
    assert measure_publication(measure) == publication


def _row(**values: str) -> dict[str, Any]:
    return {name: {"type": "literal", "value": value} for name, value in values.items()}


def test_a_page_of_rows_is_a_measure_each() -> None:
    rows = [
        _row(id="268378", modified="2019-02-01", celex="32016L0680", number="401"),
        _row(id="268378", modified="2019-02-01", celex="32016L0680", title=" Wet "),
        _row(id="268378", modified="2019-02-01", celex="32016L0681"),
        _row(id="270599", modified="2019-03-25"),  # implements nothing CELLAR resolves
    ]
    assert _measures(rows) == [
        {
            "id": "268378",
            "modified": "2019-02-01",
            "celex": ["32016L0680", "32016L0681"],
            "number": "401",
            "title": "Wet",
        },
        {"id": "270599", "modified": "2019-03-25", "celex": []},
    ]


def test_a_page_is_asked_by_key_and_window() -> None:
    query = _measures_sparql("NLD", "2026-01-01", "268378")
    assert 'FILTER(STR(?id) > "268378")' in query
    assert '"2026-01-01T00:00:00"' in query
    assert "country/NLD" in query and "OFFSET" not in query
    assert "?modified >=" not in _measures_sparql("NLD", None, "")
