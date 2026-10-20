"""A law the Staatsblad published and the BWB does not hold yet, for real: excerpts of the XML
of Stb. 2026, 56 (the new Wetboek van Strafvordering, dossier 36327) and Stb. 2026, 57 (the
Tweede vaststellingswet, dossier 36636, which gives Boek 1, Hoofdstuk 10 and Boek 7 their
text), as ``retrieve staatsblad`` stores them, through ``normalize staatsblad-laws`` and
``semantic staatsblad-law-references``, then the API.

- The law is an instrument with its articles, read as the BWB reads a law, with its status:
  enacted, not in force.
- Its publications enact (``ESTABLISHES``) and introduce (``INTRODUCES``) its articles and
  are ``LEGISLATED_IN`` their dossiers.
- An article that names another of the law refers to it.
- Its articles are read, listed and found as those of a law of the BWB.
- Once the BWB holds the law, the law of the Staatsblad goes, with its articles.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import RAW_KIND_STAATSBLAD_LAW, SOURCE_STAATSBLAD
from lawgraph.db import GraphStore, RawSourceWriter, raw_source_doc

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
LAW = "instruments/wet_stb_2026_56"


def _node(key: str, node_type: str, **props: Any) -> dict[str, Any]:
    return {"key": key, "type": node_type, "labels": ["TK"], "props": props}


def _seed(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "dossiers",
        [
            _node("36327", "dossier", number="36327", label="36327"),
            _node("36636", "dossier", number="36636", label="36636"),
        ],
    )
    with RawSourceWriter(store) as writer:
        for official in ("stb-2026-56", "stb-2026-57"):
            writer.add(
                raw_source_doc(
                    source=SOURCE_STAATSBLAD,
                    kind=RAW_KIND_STAATSBLAD_LAW,
                    external_id=official,
                    payload_text=(
                        FIXTURES / f"{official.replace('-', '_')}_excerpt.xml"
                    ).read_text(),
                    meta={"identifier": official},
                )
            )


@pytest.fixture()
def client(database: str, cli: Any) -> Iterator[TestClient]:
    store = GraphStore()
    _seed(store)
    cli("normalize", "staatsblad-laws")
    cli("normalize", "staatsblad-laws")  # a second run changes nothing
    cli("semantic", "staatsblad-law-references")
    cli("semantic", "graph-list-stats")
    app.dependency_overrides[get_store] = lambda: store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_store, None)


def _get(client: TestClient, path: str) -> Any:
    response = client.get(path)
    assert response.status_code == 200, (path, response.text[:500])
    return response.json()


def _edges(relation: str) -> set[tuple[str, str]]:
    return {
        (row["from_id"], row["to_id"])
        for row in GraphStore().query(
            "SELECT from_id, to_id FROM edges WHERE relation = %(r)s", {"r": relation}
        )
    }


def test_the_law_is_an_instrument_enacted_and_not_in_force(client: TestClient) -> None:
    law = _get(client, "/api/instruments/wet_stb_2026_56")
    assert law["display_name"] == "Wetboek van Strafvordering (Stb. 2026, 56)"
    assert law["citation_title"] == "Wetboek van Strafvordering"
    assert (law["status"], law["in_force"]) == ("vastgesteld", False)
    assert (law["kind"], law["jurisdiction"]) == ("wet", "nl")
    assert law["official_id"] == "stb-2026-56"
    assert law["dossier_numbers"] == ["36327", "36636"]
    assert law["path"] == "/wetten/STB-2026-56"
    assert (
        law["official_url"]
        == "https://zoek.officielebekendmakingen.nl/stb-2026-56.html"
    )
    assert law["article_count"] == 7


def test_its_publications_enact_its_articles_in_their_dossiers(
    client: TestClient,
) -> None:
    assert (
        "instruments/stb_2026_56",
        "articles/stb_2026_56_2_8_6",
    ) in _edges("ESTABLISHES")
    assert _edges("INTRODUCES") == {
        ("instruments/stb_2026_57", "articles/stb_2026_56_1_10_1"),
        ("instruments/stb_2026_57", "articles/stb_2026_56_7_1_1"),
    }
    assert _edges("LEGISLATED_IN") == {
        ("instruments/stb_2026_56", "dossiers/36327"),
        ("instruments/stb_2026_57", "dossiers/36636"),
    }
    assert ("articles/stb_2026_56_2_8_6", LAW) in _edges("PART_OF")


def test_an_article_reads_as_one_of_the_bwb(client: TestClient) -> None:
    body = _get(client, "/api/articles/STB-2026-56/2.8.6")
    article = body["article"]
    assert article["official_id"] == "stb-2026-56"
    assert article["path"] == "/wetten/STB-2026-56/artikel/2.8.6"
    assert article["text"].startswith("1. De officier van justitie kan")
    assert body["instrument"]["key"] == "wet_stb_2026_56"
    # "bedoeld in artikel 2.8.16": the article of the same law
    (citation,) = body["citations"]
    assert citation["target"]["id"] == "articles/stb_2026_56_2_8_16"
    assert citation["text"] == "2.8.16"


def test_an_article_has_one_version_the_enacted_text(client: TestClient) -> None:
    history = _get(client, "/api/articles/STB-2026-56/2.8.6/history")
    (listed,) = history["versions"]
    assert listed["key"] == "stb_2026_56_2_8_6"
    assert (listed["valid_from"], listed["current"]) == (None, False)
    assert (listed["change"], listed["text_changed"]) == ("establishes", True)
    assert listed["amended_by"]["id"] == "stb-2026-56"
    assert listed["amended_by"]["official_url"] == (
        "https://zoek.officielebekendmakingen.nl/stb-2026-56.html"
    )
    assert [d["number"] for d in listed["amended_by"]["dossiers"]] == ["36327"]
    assert listed["commencement"] is None

    version = _get(client, "/api/articles/STB-2026-56/2.8.6/history/stb_2026_56_2_8_6")
    article = _get(client, "/api/articles/STB-2026-56/2.8.6")["article"]
    assert version["text"] == article["text"]
    assert [p["number"] for p in version["parts"] if p["kind"] == "lid"] == ["1", "2"]
    assert client.get("/api/articles/STB-2026-56/2.8.6/history/x").status_code == 404

    # a text another law gave: that law made the version
    (introduced,) = _get(client, "/api/articles/STB-2026-56/7.1.1/history")["versions"]
    assert (introduced["change"], introduced["amended_by"]["id"]) == (
        "introduces",
        "stb-2026-57",
    )


def test_the_articles_of_the_law_in_their_order(client: TestClient) -> None:
    for identifier in ("wet_stb_2026_56", "STB-2026-56"):
        body = _get(client, f"/api/instruments/{identifier}/articles")
        assert [a["article_number"] for a in body["items"]] == [
            "1.1.1",
            "1.1.2",
            "1.10.1",
            "2.8.6",
            "2.8.16",
            "7.1.1",
            "9.3",
        ]
    item = next(a for a in body["items"] if a["article_number"] == "1.10.1")
    assert item["path"] == "/wetten/STB-2026-56/artikel/1.10.1"
    assert [c["label"] for c in item["breadcrumb"]] == ["Boek 1", "Hoofdstuk 10"]


def test_the_address_of_the_law_and_its_article_is_looked_up(
    client: TestClient,
) -> None:
    law = _get(client, "/api/lookup?kind=law&id=STB-2026-56")
    assert law["id"] == LAW
    article = _get(client, "/api/lookup?kind=article&law=STB-2026-56&number=2.8.6")
    assert article["id"] == "articles/stb_2026_56_2_8_6"


def test_the_words_of_an_article_find_it(client: TestClient) -> None:
    hits = _get(client, "/api/search?q=onbekende%20kwetsbaarheid&types=articles")
    ids = [hit["id"] for hit in hits["results"]["articles"]]
    assert "articles/stb_2026_56_2_8_6" in ids


def test_the_law_goes_once_the_bwb_holds_it(client: TestClient, cli: Any) -> None:
    store = GraphStore()
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            {
                "key": "bwbr0051234",
                "type": "instrument",
                "labels": ["BWB"],
                "props": {
                    "bwb_id": "BWBR0051234",
                    "kind": "wet",
                    "citation_title": "Wetboek van Strafvordering",
                    "enacted_publication": "stb-2026-56",
                },
            }
        ],
    )
    cli("normalize", "staatsblad-laws")
    assert not store.has_node("instruments", "wet_stb_2026_56")
    left = list(store.query("SELECT key FROM articles WHERE official_id IS NOT NULL"))
    assert left == []
    assert _edges("REFERS_TO") == set()
    assert client.get("/api/lookup?kind=law&id=STB-2026-56").status_code == 404
