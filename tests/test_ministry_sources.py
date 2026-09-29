"""The ministry table from TOOI and the cabinet pages, and the names of ministries over time.

The fixtures are version 6 of the TOOI list ``rwc_ministeries_compleet`` (published
24 February 2026) and the Rijksoverheid cabinet pages (read on 25 September 2026).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lawgraph.clients.tooi import latest_version
from lawgraph.core.cabinet_sources import build_cabinets
from lawgraph.core.ministries import (
    CURATED,
    DATA,
    MINISTRY_BY_KEY,
    classify_function,
    current_on,
)
from lawgraph.core.ministry_sources import build_ministries, tooi_names
from lawgraph.core.rijksoverheid import parse_page

FIXTURES = Path(__file__).parent / "fixtures"
TOOI = json.loads((FIXTURES / "tooi_ministeries.json").read_text())


def _pages() -> list[dict]:
    return [
        {"slug": p.stem, "url": "u", "read_on": "r", "page": parse_page(p.read_text())}
        for p in sorted((FIXTURES / "rijksoverheid").glob("*.html"))
    ]


def test_tooi_gives_every_name_with_its_days_and_the_decree_that_ended_it() -> None:
    names = {(n["tooi"], n["name"]): n for n in tooi_names(TOOI)}
    justitie = names[("mnre1058", "Justitie")]
    assert (justitie["until"], justitie["abbreviation"]) == ("2010-11-30", "MinJus")
    assert (
        justitie["basis"]
        == "https://zoek.officielebekendmakingen.nl/stcrt-2010-16523.html"
    )
    assert names[("mnre1058", "Veiligheid en Justitie")]["from"] == "2010-12-01"
    assert names[("mnre1162", "Asiel en Migratie")]["until"] == "2026-02-22"
    # a name that comes back: Economische Zaken is a name of mnre1045 twice
    assert sorted(
        (n["from"], n["until"])
        for n in tooi_names(TOOI)
        if n["tooi"] == "mnre1045" and n["name"] == "Economische Zaken"
    ) == [("2013-01-01", "2017-12-31"), ("2024-07-02", "2026-02-22")]


def test_the_data_file_is_what_the_sources_give() -> None:
    """``data/ministries.json`` is the build of the fixtures and the curated list: nothing
    in it was edited by hand, and every curated name has a source."""
    current = json.loads(DATA.read_text(encoding="utf-8"))
    curated = json.loads(CURATED.read_text(encoding="utf-8"))
    rebuilt, dropped = build_ministries(
        curated, TOOI, build_cabinets(_pages(), lambda text: None)
    )
    assert rebuilt == current["ministries"]
    assert dropped == []
    sources = {p["source"] for m in rebuilt for p in m["periods"]}
    assert sources <= {"tooi", "rijksoverheid"}
    assert {p.get("successor_source") for m in rebuilt for p in m["periods"]} <= {
        None,
        "curated",
    }


def test_a_curated_name_no_source_names_is_left_out() -> None:
    curated = {
        "ministries": [
            {"key": "az", "name": "Algemene Zaken"},
            {"key": "opw", "name": "Openbare Werken"},
        ],
        "successions": {"opw": "venw"},
    }
    table, dropped = build_ministries(
        curated, TOOI, build_cabinets(_pages(), lambda text: None)
    )
    assert dropped == ["opw"]
    assert "opw" not in {m["key"] for m in table}


def test_every_succession_and_period_in_the_table_holds() -> None:
    for ministry in MINISTRY_BY_KEY.values():
        assert ministry.periods, ministry.key
        for period in ministry.periods:
            assert period.successor is None or period.successor in MINISTRY_BY_KEY
            assert not (period.from_date and period.until) or (
                period.from_date <= period.until
            ), ministry.key
        ends = [p.until for p in ministry.periods]
        assert None not in ends[:-1], (
            f"{ministry.key}: only the last period may be open"
        )


@pytest.mark.parametrize(
    ("key", "day", "current"),
    [
        ("ez", "2009-01-01", "ez"),
        ("ez", "2011-06-01", "eli"),  # merged with LNV into ELenI on 14 October 2010
        ("ez", "2014-01-01", "ez"),
        ("ez", "2020-01-01", "ezk"),
        ("ez", "2025-01-01", "ez"),
        ("ez", "2026-03-19", "ezk"),  # Economische Zaken en Klimaat again under Jetten
        ("justitie", "2011-06-01", "venj"),
        ("justitie", "2019-01-01", "jenv"),
        ("venw", "2011-01-01", "ienm"),  # merged with VROM into IenM
        ("venw", "2020-01-01", "ienw"),
        ("biza", "2025-01-01", "bzk"),  # the handover on the pages: 3 August 1998
        ("oorlog", "1960-01-01", "def"),
        ("aenm", "2026-06-01", "aenm"),  # TOOI names no successor
    ],
)
def test_a_name_on_a_day_means_the_name_it_then_had(
    key: str, day: str, current: str
) -> None:
    assert current_on(key, day) == current


def test_a_function_is_read_with_the_name_of_its_day() -> None:
    assert classify_function(
        "Minister van Veiligheid en Justitie", on="2016-01-01"
    ) == (
        "minister",
        "venj",
    )
    assert classify_function("minister van Justitie", on="2019-01-01") == (
        "minister",
        "jenv",
    )


def test_the_page_of_the_list_links_its_versions() -> None:
    page = (
        '<a href="expression?lijst_uri=https%3A%2F%2Fidentifier.overheid.nl%2Ftooi%2Fset'
        '%2Frwc_ministeries_compleet%2F5">5</a><a href="expression?lijst_uri=https%3A%2F'
        '%2Fidentifier.overheid.nl%2Ftooi%2Fset%2Frwc_ministeries_compleet%2F6">6</a>'
    )
    assert latest_version(page) == 6
    assert latest_version("<html></html>") is None
