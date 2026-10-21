"""The annexes of the Cyberbeveiligingswet (BWBR0052872) on its real XML (its shortest
article and its two annexes, tables of sectors with their footnotes): the real ``normalize
bwb``, then the API.

- The table of contents of the law names its annexes after its articles, as their heading
  prints them, each with its address.
- An annex has its text as an article has it: its table a table of that text, its footnotes
  paragraphs, its links to EU acts its references.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from lawgraph.config.constants import RAW_KIND_BWB_TOESTAND
from lawgraph.db import GraphStore
from tests.asserts import show_items
from tests.databases import Api, module_store
from tests.integration.seed import write_toestanden
from tests.paths import fixture_text

LAW = "BWBR0052872"

pytestmark = pytest.mark.xdist_group("annex_tables")


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Iterator[GraphStore]:
    """Built once for the tests here, on a database of its own: they only read it."""
    with module_store(tmp_path_factory) as (store, cli):
        write_toestanden(
            store,
            [
                (
                    RAW_KIND_BWB_TOESTAND,
                    LAW,
                    fixture_text("bwb_cbw_annexes_toestand.xml"),
                    {
                        "bwb_id": LAW,
                        "state_url": f"https://repo/{LAW}/2026-08-15.xml",
                        "start_date": "2026-08-15",
                        "end_date": "9999-12-31",
                    },
                )
            ],
        )
        cli("normalize", "bwb")
        yield store


def test_the_table_of_contents_names_the_annexes_after_the_articles(
    api: Api,
) -> None:
    listed = api.get_json(f"/api/instruments/{LAW}/articles")
    assert [item["article_number"] for item in listed["items"]] == ["6"]
    rows = [
        (a["key"], a["label"], a["display_name"], a["title"], a["path"])
        for a in listed["annexes"]
    ]
    assert rows == [
        ("bwbr0052872_annex_1", "1", "Bijlage 1", None, f"/wetten/{LAW}/bijlage/1"),
        ("bwbr0052872_annex_2", "2", "Bijlage 2", None, f"/wetten/{LAW}/bijlage/2"),
    ]
    assert listed["annexes"][0]["text_preview"].startswith("Sector\tSubsector")


def test_an_annex_has_its_table_and_its_links(api: Api) -> None:
    body = api.get_json(f"/api/annexes/{LAW.lower()}_annex_1")
    annex = body["annex"]
    text = annex["text"]
    (table,) = annex["tables"]
    rows = text[table["start"] : table["end"]].split("\n")
    assert rows[0].split("\t") == ["Sector", "Subsector", "Soort entiteit"]
    assert (table["head_rows"], table["columns"]) == (1, 3)
    assert {"row": 1, "cell": 0, "cols": 1, "rows": 17} in table["spans"]
    assert text[table["end"] :].lstrip().startswith("1 Richtlijn (EU) 2019/944")
    celex = {ref["celex"] for ref in body["references"]}
    assert "32019L0944" in celex
    failing = [
        r for r in body["references"] if text[r["start"] : r["end"]] != r["text"]
    ]
    assert not failing, show_items(failing)
