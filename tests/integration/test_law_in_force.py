"""The law in force on a date: at most one version of an article, and never one that lapsed,
that left the law or that only announced the article. The real ``normalize bwb-history`` on
two toestanden of one law, and the at-date and history routes.

- Article 142 is in the first toestand and gone from the second: it ends when the second
  starts (the old inheritance law of BW Boek 4 left the law in 2003 this way).
- Article 101 lapsed ("Vervallen"): that version says the article ended, it is no text.
- Article 82 is "Dit onderdeel is nog niet inwerking getreden" in the first toestand and has
  its text, under the same versie-id, in the second: the version is the text.
- The toestanden end inclusively in the source; the graph ends every period exclusively.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    RAW_KIND_BWB_TOESTAND,
    RAW_KIND_BWB_TOESTAND_ALL,
    SOURCE_BWB,
)
from lawgraph.db import ArangoStore, RawSourceWriter, raw_source_doc

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
LAW = "BWBR0001840"
XML = (FIXTURES / "bwb_grondwet_toestand.xml").read_text()
PLACEHOLDER = "Dit onderdeel is nog niet inwerking getreden"


def _article_82_announced(xml: str) -> str:
    """Article 82 as a toestand before its commencement shows it: a placeholder."""
    start = xml.index('bwb-ng-variabel-deel="/Hoofdstuk5/Paragraaf1/Artikel82"')
    end = xml.index("</artikel>", start)
    body = xml[start:end]
    kop_end = body.index("</kop>") + len("</kop>")
    return xml[:start] + body[:kop_end] + f"<al>{PLACEHOLDER}</al>" + xml[end:]


def _without_article_142(xml: str) -> str:
    return re.sub(
        r'<artikel bwb-ng-variabel-deel="/Hoofdstuk8/Artikel142".*?</artikel>',
        "",
        xml,
        count=1,
        flags=re.S,
    )


FIRST = _article_82_announced(XML)
SECOND = _without_article_142(XML)


def _seed(store: ArangoStore) -> None:
    toestanden = [
        (RAW_KIND_BWB_TOESTAND, LAW, SECOND, "2025-01-01", None),
        (
            RAW_KIND_BWB_TOESTAND_ALL,
            f"{LAW}@2018-12-21",
            FIRST,
            "2018-12-21",
            "2024-12-31",
        ),
        (
            RAW_KIND_BWB_TOESTAND_ALL,
            f"{LAW}@2025-01-01",
            SECOND,
            "2025-01-01",
            "9999-12-31",
        ),
    ]
    with RawSourceWriter(store) as writer:
        for kind, external_id, xml, start, end in toestanden:
            writer.add(
                raw_source_doc(
                    source=SOURCE_BWB,
                    kind=kind,
                    external_id=external_id,
                    payload_text=xml,
                    meta={
                        "bwb_id": LAW,
                        "state_url": f"https://repo/{LAW}/{start}.xml",
                        "start_date": start,
                        "end_date": end,
                    },
                )
            )


@pytest.fixture()
def client(database: str, cli: Any) -> Iterator[TestClient]:
    store = ArangoStore()
    _seed(store)
    cli("normalize", "bwb")
    cli("normalize", "bwb-history")
    cli("normalize", "bwb-history")  # a second run changes nothing
    app.dependency_overrides[get_store] = lambda: store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_store, None)


def _get(client: TestClient, path: str) -> Any:
    response = client.get(path)
    assert response.status_code == 200, (path, response.text[:500])
    return response.json()


def _numbers_on(client: TestClient, date: str) -> list[str]:
    body = _get(client, f"/api/instruments/{LAW}/articles/at/{date}?limit=500")
    return [a["article_number"] for a in body["items"]]


def test_the_law_on_a_date_has_each_article_once_and_only_in_force(
    client: TestClient,
) -> None:
    before, after = _numbers_on(client, "2020-01-01"), _numbers_on(client, "2026-01-01")
    assert len(before) == len(set(before)) and len(after) == len(set(after))
    assert "142" in before and "142" not in after  # it left the law
    assert "101" not in before and "101" not in after  # it lapsed in 1995


def test_an_article_that_left_the_law_ends_when_the_next_toestand_starts(
    client: TestClient,
) -> None:
    versions = list(
        ArangoStore().query(
            "FOR v IN article_versions FILTER v.props.article_number == '142' "
            "RETURN [v.props.valid_until, v.props.current]"
        )
    )
    assert versions == [["2025-01-01", False]]


def test_a_lapsed_version_is_no_text_in_force(client: TestClient) -> None:
    body = _get(client, f"/api/articles/{LAW}/101/history")
    assert not [v for v in body["versions"] if v["current"]]


def test_an_announced_article_has_the_text_it_came_into_force_with(
    client: TestClient,
) -> None:
    versions = _get(client, f"/api/articles/{LAW}/82/history")["versions"]
    assert versions and all(PLACEHOLDER not in (v["text"] or "") for v in versions)


def test_every_period_ends_exclusively_and_an_open_one_is_null(
    client: TestClient,
) -> None:
    toestanden = _get(client, f"/api/instruments/{LAW}/versions")["items"]
    assert sorted((v["valid_from"], v["valid_until"]) for v in toestanden) == [
        ("2018-12-21", "2025-01-01"),
        ("2025-01-01", None),
    ]
