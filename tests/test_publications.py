"""The official publications: their KOOP id and how they are cited."""

from __future__ import annotations

import pytest

from lawgraph.core.bwb_xml import publication_display_name
from lawgraph.core.publications import (
    koop_citation,
    koop_id,
    parse_koop_id,
    publication_citation,
    publication_series,
)


@pytest.mark.parametrize(
    ("series", "cited"),
    [("stb", "Stb. 2026, 94"), ("stcrt", "Stcrt. 2026, 94"), ("trb", "Trb. 2026, 94")],
)
def test_a_publication_is_cited_by_series_year_and_number(
    series: str, cited: str
) -> None:
    assert publication_citation(publication_series(series), 2026, "94") == cited  # type: ignore[arg-type]
    assert koop_citation(koop_id(series, 2026, 94)) == cited


def test_the_koop_id_is_read_and_made() -> None:
    assert koop_id("Stb", 2019, "33") == "stb-2019-33"
    assert parse_koop_id("stcrt-2020-00012") == ("stcrt", 2020, "00012")
    assert koop_citation("stcrt-2020-00012") == "Stcrt. 2020, 12"
    assert parse_koop_id("Trb-1951-154") == ("trb", 1951, "154")
    assert parse_koop_id("bwbr-1951-154") is None
    assert koop_citation("stb-2019") is None


def test_the_series_is_read_from_the_bwb_kind() -> None:
    assert publication_series("Stb") == "stb"
    assert publication_series(" STCRT ") == "stcrt"
    assert publication_series("PbEU") is None
    assert publication_series(None) is None


def test_a_bwb_publication_is_named_by_its_citation_else_its_id() -> None:
    assert (
        publication_display_name({"kind": "Stb", "year": 2019, "number": "33"})
        == "Stb. 2019, 33"
    )
    assert (
        publication_display_name({"kind": "Stb", "id": "stb-2019-33"}) == "stb-2019-33"
    )
