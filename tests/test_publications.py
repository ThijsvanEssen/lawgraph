"""The official publications: their KOOP id and how they are cited."""

from __future__ import annotations

import pytest

from lawgraph.core.bwb_xml import publication_display_name
from lawgraph.core.publications import (
    instrument_key,
    koop_citation,
    koop_id,
    note_key,
    official_of_instrument_key,
    official_of_note_key,
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


@pytest.mark.parametrize(
    ("official", "note", "instrument"),
    [
        ("stb-2026-94", "stb_stb_2026_94", "stb_2026_94"),
        ("trb-2024-12", "trb_trb_2024_12", "trb_2024_12"),
        ("stcrt-2020-00012", "stcrt_stcrt_2020_00012", "stcrt_2020_00012"),
    ],
)
def test_the_keys_of_a_publication_and_back(
    official: str, note: str, instrument: str
) -> None:
    """Its nota van toelichting is a document of its own source (``stb_stb_…``), the
    publication the BWB names an instrument (``stb_…``): stored keys, so fixed."""
    assert note_key(official) == note
    assert instrument_key(official) == instrument
    assert official_of_note_key(note) == official
    assert official_of_instrument_key(instrument) == official
