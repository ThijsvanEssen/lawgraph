"""The annexes of a law and the law itself, on trimmed real XML of the Awb (BWBR0005537):
articles 8:5 and 8:6 and bijlage 2 with its articles 1 and 4. The real ``normalize bwb``,
``normalize bwb-history``, ``semantic bwb-annexes`` and ``semantic graph-list-stats``, then
the API.

- The entries of bijlage 2 say the law they fall under and the item they are nested in.
- Articles 8:5 and 8:6 name bijlage 2 by its name ("de bij deze wet behorende
  Bevoegdheidsregeling bestuursrechtspraak"): they are its ``referenced_by``.
- The dates of the Awb are those of the Awb itself (signed 1992-06-04, in force
  1994-01-01), not of the amendment of 2012 its current version names.
- The article count of the Awb counts its articles, not its annex.
- An article of a bijlage (which has no versie-id) has a version per text, not per toestand.
- The parts of an article of a bijlage cover its whole text, the lines between its lists too.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote

import pytest

from lawgraph.config.constants import (
    RAW_KIND_BWB_TOESTAND,
    RAW_KIND_BWB_TOESTAND_ALL,
)
from lawgraph.db import GraphStore
from tests.asserts import show_items
from tests.databases import Api, module_store
from tests.integration.seed import write_toestanden

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
LAW = "BWBR0005537"
XML = (FIXTURES / "bwb_awb_annexes_toestand.xml").read_text()
# A line of bijlage 2 artikel 4 that the newest toestand changes.
CHANGED_LINE = "Winkeltijdenwet"


def _toestand(start: str, *, changed: bool) -> str:
    xml = re.sub(
        r'inwerkingtreding="\d{4}-\d\d-\d\d"',
        f'inwerkingtreding="{start}"',
        XML,
        count=1,
    )
    return xml.replace(CHANGED_LINE, f"{CHANGED_LINE} 2026") if changed else xml


def _seed(store: GraphStore) -> None:
    toestanden = [
        (RAW_KIND_BWB_TOESTAND, LAW, "2026-08-15", "9999-12-31", True),
        # the history, newest first: a version begins in the first toestand of its text
        (
            RAW_KIND_BWB_TOESTAND_ALL,
            f"{LAW}@2026-08-15",
            "2026-08-15",
            "9999-12-31",
            True,
        ),
        (
            RAW_KIND_BWB_TOESTAND_ALL,
            f"{LAW}@2025-01-01",
            "2025-01-01",
            "2026-08-14",
            False,
        ),
        (
            RAW_KIND_BWB_TOESTAND_ALL,
            f"{LAW}@2024-01-01",
            "2024-01-01",
            "2024-12-31",
            False,
        ),
    ]
    write_toestanden(
        store,
        [
            (
                kind,
                external_id,
                _toestand(start, changed=changed),
                {
                    "bwb_id": LAW,
                    "state_url": f"https://repo/{LAW}/{start}.xml",
                    "start_date": start,
                    "end_date": end,
                },
            )
            for kind, external_id, start, end, changed in toestanden
        ],
    )


# The tests read one database built for them all (``store``), on the worker that built it.
pytestmark = pytest.mark.xdist_group("annexes")


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Iterator[GraphStore]:
    """Built once for the tests here, on a database of its own: they only read it."""
    with module_store(tmp_path_factory) as (store, cli):
        _seed(store)
        cli("normalize", "bwb")
        cli("normalize", "bwb-history")
        cli("normalize", "bwb-history")  # a second run changes nothing
        cli("semantic", "bwb-annexes")
        cli("semantic", "graph-list-stats")
        yield store


def _article(number: str) -> str:
    return f"/api/articles/{LAW}/{quote(number)}"


def test_an_annex_entry_names_its_law_and_the_entry_it_is_nested_in(
    api: Api,
) -> None:
    entries = api.get_json("/api/annexes/bwbr0005537_annex_2")["annex"]["entries"]
    by_name = {e["name"]: e for e in entries}

    boek_1 = by_name["a. Boek 1:"]
    nested = [e for e in entries if e["parent_index"] == boek_1["index"]]
    assert [e["name"] for e in nested] == [
        "1. artikel 7, eerste en tweede lid",
        "2. titel 14, afdeling 4",
    ]
    assert {e["heading"] for e in [boek_1, *nested]} == {"Burgerlijk Wetboek"}
    assert boek_1["parent_index"] is None
    assert by_name["a. artikel 49"]["heading"] == "Gemeentewet"
    # an item is its own text: the items nested in it are not repeated in it
    failing = [e for e in entries if e is not nested[0] if "1. artikel 7" in e["name"]]
    assert not failing, show_items(failing)


def test_the_articles_naming_an_annex_are_its_referenced_by(api: Api) -> None:
    body = api.get_json("/api/annexes/bwbr0005537_annex_2")
    referring = {item["article"]["article_number"] for item in body["referenced_by"]}
    # not its own articles, which name it too
    assert referring == {"8:5", "8:6"}


def test_the_dates_of_a_law_are_those_of_the_law_itself(api: Api) -> None:
    awb = api.get_json(f"/api/instruments/{LAW}")
    assert (awb["date_signed"], awb["date_published"], awb["date_in_force"]) == (
        "1992-06-04",
        "1992-06-30",
        "1994-01-01",
    )
    assert awb["version_date_in_force"] == "2026-08-15"


def test_the_article_count_of_a_law_is_that_of_its_article_list(
    api: Api,
) -> None:
    awb = api.get_json(f"/api/instruments/{LAW}")
    listed = api.get_json(f"/api/instruments/{LAW}/articles?limit=500")
    assert awb["article_count"] == listed["total"] == 4


def test_an_article_of_an_annex_has_a_version_per_text(api: Api) -> None:
    unchanged = api.get_json(_article("bijlage 2 artikel 1") + "/history")["versions"]
    assert [v["valid_from"] for v in unchanged] == ["2024-01-01"]
    assert unchanged[0]["valid_until"] is None

    changed = api.get_json(_article("bijlage 2 artikel 4") + "/history")["versions"]
    assert [(v["valid_from"], v["valid_until"]) for v in changed] == [
        ("2024-01-01", "2026-08-15"),
        ("2026-08-15", None),
    ]


def test_the_parts_of_an_article_of_an_annex_cover_its_text(api: Api) -> None:
    article = api.get_json(_article("bijlage 2 artikel 4"))["article"]
    text, parts = article["text"], article["parts"]
    covered = [False] * len(text)
    for part in parts:
        covered[part["start"] : part["end"]] = [True] * (part["end"] - part["start"])
    # what no part covers is whitespace and the printed numbers ("a.", "1°.")
    rest = "".join(c if not hit else " " for c, hit in zip(text, covered, strict=True))
    assert re.fullmatch(r"(\s|\w{1,3}°?\.)*", rest), rest[:200]
    tekst = [p for p in parts if p["kind"] == "tekst"]
    assert any(p["text"].startswith("Energiewet, met inbegrip van") for p in tekst), (
        show_items(tekst)
    )


def test_an_annex_names_its_law_in_its_title_as_its_page_does(
    api: Api,
) -> None:
    """Its props keep the name of its law (``normalize bwb``), so the title of the API is
    the title of its server page (one source: the tab does not change)."""
    import re

    node = api.get_json("/api/nodes/annexes/bwbr0005537_annex_2?limit=1")
    assert "Algemene wet bestuursrecht" in node["title"]
    html = api.get(f"/render{node['path']}").text
    title = re.search(r"<title[^>]*>([^<]*)</title>", html)
    assert title and title[1] == f"{node['title']}, Concordans"


def test_the_table_of_contents_of_a_law_holds_its_annexes(api: Api) -> None:
    """Bijlage 2 is articles only: its articles are items, the annex itself an annex with
    no text of its own."""
    listed = api.get_json(f"/api/instruments/{LAW}/articles")
    (annex,) = listed["annexes"]
    assert (annex["key"], annex["display_name"], annex["path"]) == (
        "bwbr0005537_annex_2",
        "Bijlage 2",
        f"/wetten/{LAW}/bijlage/2",
    )
    assert annex["title"].startswith("Bevoegdheidsregeling bestuursrechtspraak")
    assert annex["text_preview"] is None
    numbers = [item["article_number"] for item in listed["items"]]
    assert numbers[-2:] == ["bijlage 2 artikel 1", "bijlage 2 artikel 4"]
