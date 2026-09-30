"""Republications of the Grondwet, on trimmed real XML (BWBR0001840): the real ``normalize
bwb``, ``normalize bwb-history`` (twice) and ``semantic bwb-amendments``, then the API.

Article 7 as the history has it: changed in 2002 (Stb. 2002, 144), then placed again with the
same text by the republications of 2008 (Stb. 2008, 348) and 2019 (Stb. 2019, 33), each with a
``versie-id`` of its own. Article 82 is only known from the republication of 2019.

- A republication (effect ``tekstplaatsing-*``) is no amendment: no AMENDS from it.
- Consecutive versions of an article with the same text are one version, which begins with
  the first of them and is amended by the publication that made the text.
- The publication a republication was is gone from the amending publications of the law.
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
ARTICLE_7 = re.compile(
    r'<artikel bwb-ng-variabel-deel="/Hoofdstuk1/Artikel7".*?</artikel>', re.DOTALL
)
LID_4 = "De voorgaande leden zijn niet van toepassing op het maken van handelsreclame."


def _article_7(
    *, versie: str, start: str, effect: str, stb: tuple[int, int], signed: str
) -> str:
    """Article 7 as a toestand of *start* holds it: its version, publication and effect."""
    year, number = stb
    block = ARTICLE_7.search(XML)
    assert block is not None
    article = block.group(0)
    article = re.sub(r'versie-id="\d+"', f'versie-id="{versie}"', article, count=1)
    article = re.sub(r'inwerking="[\d-]+"', f'inwerking="{start}"', article, count=1)
    article = re.sub(r'bron="[^"]+"', f'bron="Stb.{year}-{number}"', article, count=1)
    article = article.replace("tekstplaatsing-wijziging", effect)
    origin = (
        f'<publicatie effect="{effect}" soort="Stb" urlidentifier="stb-{year}-{number}">'
        f"<publicatiejaar>{year}</publicatiejaar><publicatienr>{number}</publicatienr>"
        f'<ondertekeningsdatum isodatum="{signed}">x</ondertekeningsdatum></publicatie>'
    )
    return re.sub(
        r"<oorspronkelijk>.*?</oorspronkelijk>",
        f"<oorspronkelijk>{origin}</oorspronkelijk>",
        article,
        count=1,
        flags=re.DOTALL,
    )


def _toestand(start: str, article_7: str | None) -> str:
    xml = re.sub(
        r'inwerkingtreding="\d{4}-\d\d-\d\d"',
        f'inwerkingtreding="{start}"',
        XML,
        count=1,
    )
    return ARTICLE_7.sub(lambda _: article_7, xml) if article_7 else xml


# (start, end, article 7 of the toestand or None for the fixture's own)
_HISTORY = [
    (
        "2002-03-21",
        "2008-07-14",
        _article_7(
            versie="4000001",
            start="2002-03-21",
            effect="wijziging",
            stb=(2002, 144),
            signed="2002-02-27",
        ),
    ),
    (
        "2008-07-15",
        "2018-12-20",
        _article_7(
            versie="4000002",
            start="2008-07-15",
            effect="tekstplaatsing-vernummering",
            stb=(2008, 348),
            signed="2008-08-22",
        ),
    ),
    ("2018-12-21", "9999-12-31", None),
]


def _seed(store: ArangoStore) -> None:
    with RawSourceWriter(store) as writer:
        writer.add(
            raw_source_doc(
                source=SOURCE_BWB,
                kind=RAW_KIND_BWB_TOESTAND,
                external_id=LAW,
                payload_text=XML,
                meta={"bwb_id": LAW, "state_url": f"https://repo/{LAW}.xml"},
            )
        )
        for start, end, article_7 in _HISTORY:
            # the 2002 toestand holds another text of lid 4 than the ones after it
            xml = _toestand(start, article_7)
            if start == "2002-03-21":
                xml = xml.replace(LID_4, f"{LID_4} (2002)")
            writer.add(
                raw_source_doc(
                    source=SOURCE_BWB,
                    kind=RAW_KIND_BWB_TOESTAND_ALL,
                    external_id=f"{LAW}@{start}",
                    payload_text=xml,
                    meta={
                        "bwb_id": LAW,
                        "state_url": f"https://repo/{LAW}/{start}.xml",
                        "start_date": start,
                        "end_date": end,
                    },
                )
            )


def _with_the_2008_text(store: ArangoStore) -> None:
    """The 2002 toestand again, now with the text of 2008: all three versions are one."""
    with RawSourceWriter(store) as writer:
        start, end, article_7 = _HISTORY[0]
        writer.add(
            raw_source_doc(
                source=SOURCE_BWB,
                kind=RAW_KIND_BWB_TOESTAND_ALL,
                external_id=f"{LAW}@{start}",
                payload_text=_toestand(start, article_7),
                meta={
                    "bwb_id": LAW,
                    "state_url": f"https://repo/{LAW}/{start}.xml",
                    "start_date": start,
                    "end_date": end,
                },
            )
        )


@pytest.fixture()
def store(database: str, cli: Any) -> ArangoStore:
    store = ArangoStore()
    _seed(store)
    cli("normalize", "bwb")
    cli("normalize", "bwb-history")
    cli("normalize", "bwb-history")  # a second run changes nothing
    cli("semantic", "bwb-amendments")
    return store


@pytest.fixture()
def client(store: ArangoStore) -> Iterator[TestClient]:
    app.dependency_overrides[get_store] = lambda: store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_store, None)


def _get(client: TestClient, path: str) -> Any:
    response = client.get(path)
    assert response.status_code == 200, (path, response.text[:500])
    return response.json()


def _amending(store: ArangoStore, article: str) -> set[tuple[str, str]]:
    aql = """
    FOR a IN articles FILTER a.props.bwb_id == @law AND a.props.article_number == @nr
        FOR e IN edges FILTER e._to == a._id
            FILTER e.relation IN ["AMENDS", "INTRODUCES", "REPEALS"]
            RETURN [e.relation, e._from]
    """
    return {
        (relation, source)
        for relation, source in store.query(aql, {"law": LAW, "nr": article})
    }


def test_a_republication_amends_no_article(store: ArangoStore) -> None:
    assert _amending(store, "7") == {("AMENDS", "instruments/stb_2002_144")}
    assert _amending(store, "82") == set()


def test_versions_with_the_same_text_are_one(client: TestClient) -> None:
    versions = _get(client, f"/api/articles/{LAW}/7/history")["versions"]
    assert [
        (v["valid_from"], v["valid_until"], v["effect"], v["amended_by"]["id"])
        for v in versions
    ] == [
        ("2002-03-21", "2008-07-15", "wijziging", "stb-2002-144"),
        ("2008-07-15", None, "tekstplaatsing-vernummering", "stb-2008-348"),
    ]
    assert versions[1]["change"] == "republishes"
    assert versions[1]["current"] is True


def test_a_republication_is_no_amending_publication(client: TestClient) -> None:
    items = _get(client, f"/api/instruments/{LAW}/amended-by?limit=500")["items"]
    sources = {item["key"] for item in items}
    assert "stb_2002_144" in sources
    assert not sources & {"stb_2008_348", "stb_2019_33"}


def test_a_version_merged_away_goes_with_its_edges(
    store: ArangoStore, cli: Any, client: TestClient
) -> None:
    _with_the_2008_text(store)
    cli("normalize", "bwb-history")
    cli("semantic", "bwb-amendments")

    versions = _get(client, f"/api/articles/{LAW}/7/history")["versions"]
    assert [(v["valid_from"], v["valid_until"]) for v in versions] == [
        ("2002-03-21", None)
    ]
    assert _amending(store, "7") == {("AMENDS", "instruments/stb_2002_144")}
    dangling = """
    FOR e IN edges FILTER STARTS_WITH(e._from, "article_versions/")
        FILTER DOCUMENT(e._from) == null RETURN e._key
    """
    assert list(store.query(dangling)) == []
