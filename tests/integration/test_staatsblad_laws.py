"""A law the Staatsblad published and the BWB does not hold yet, for real: excerpts of the XML
of Stb. 2026, 56 (the new Wetboek van Strafvordering, dossier 36327) and Stb. 2026, 57 (the
Tweede vaststellingswet, dossier 36636, which gives Boek 1, Hoofdstuk 10 and Boek 7 their
text), as ``retrieve staatsblad`` stores them, through ``normalize staatsblad-laws`` and
``semantic staatsblad-law-references`` and ``semantic bwb-definitions``, then the API.

- The law is an instrument with its articles, read as the BWB reads a law, with its status:
  enacted, not in force.
- Its publications enact (``ESTABLISHES``) and introduce (``INTRODUCES``) its articles and
  are ``LEGISLATED_IN`` their dossiers.
- An article that names another of the law refers to it; one that names an article of a law
  of the BWB refers to that, each article of an enumeration with its own parts.
- Its definitions are kept and mark its terms where they hold.
- The law and each article say what the steps made of them (``enrichment``): a reference to
  a law the graph does not hold leaves its article and the law ``partial``.
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
from tests.asserts import assert_status

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
LAW = "instruments/wet_stb_2026_56"


def _node(key: str, node_type: str, **props: Any) -> dict[str, Any]:
    return {"key": key, "type": node_type, "labels": ["TK"], "props": props}


SR, TW = "BWBR0001854", "BWBR0009950"


def _law_of_the_bwb(
    bwb_id: str, title: str, abbreviation: str | None
) -> dict[str, Any]:
    return {
        "key": bwb_id.lower(),
        "type": "instrument",
        "labels": ["BWB"],
        "props": {
            "source": "bwb",
            "bwb_id": bwb_id,
            "kind": "wet",
            "title": title,
            "citation_title": title,
            "abbreviation": abbreviation,
            "short_title": abbreviation,
        },
    }


def _seed(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "dossiers",
        [
            _node("36327", "dossier", number="36327", label="36327"),
            _node("36636", "dossier", number="36636", label="36636"),
        ],
    )
    # the laws of the BWB the articles cite, not the Politiewet 2012
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _law_of_the_bwb(SR, "Wetboek van Strafrecht", "Sr"),
            _law_of_the_bwb(TW, "Telecommunicatiewet", None),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            {
                "key": f"{bwb_id.lower()}_{number.replace('.', '_')}",
                "type": "article",
                "labels": ["BWB"],
                "props": {"bwb_id": bwb_id, "article_number": number},
            }
            for bwb_id, number in [
                (SR, "98"),
                (SR, "98c"),
                (SR, "420bis"),
                (TW, "11.7a"),
            ]
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
    cli("semantic", "staatsblad-law-references")  # a second run changes nothing
    cli("semantic", "bwb-definitions")
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
    assert law["article_count"] == 11


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
    assert_status(client.get("/api/articles/STB-2026-56/2.8.6/history/x"), 404)

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
            "1.1.4",
            "1.5.1",
            "1.10.1",
            "1.11.1",
            "1.11.2",
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
    assert_status(client.get("/api/lookup?kind=law&id=STB-2026-56"), 404)
    cli("semantic", "bwb-definitions")
    kept = store.query("SELECT bwb_id FROM lg_instrument_definitions")
    assert list(kept) == []


def test_an_article_refers_to_the_articles_of_the_bwb_it_cites(
    client: TestClient,
) -> None:
    body = _get(client, "/api/articles/STB-2026-56/2.8.16")
    cited = {
        c["target"]["id"]: (c["text"], c["leden"], c["reference_kind"])
        for c in body["citations"]
    }
    # "de artikelen 98, eerste en tweede lid, 98c, eerste lid, … en 420bis, eerste lid,
    # van het Wetboek van Strafrecht": each article with its own leden
    assert cited["articles/bwbr0001854_98"] == ("98", ["1", "2"], "extref")
    assert cited["articles/bwbr0001854_98c"] == ("98c", ["1"], "extref")
    assert cited["articles/bwbr0001854_420bis"] == ("420bis", ["1"], "extref")
    assert cited["articles/bwbr0009950_11_7a"][0] == "11.7a"
    # an article of the Wetboek van Strafrecht that is not loaded: a stub
    assert "articles/bwbr0001854_138ab" in cited
    # the Politiewet 2012 is not in the graph, nor are 2.8.13 and 2.8.15 in the excerpt:
    # not linked, and said so
    assert body["enrichment"] == {"references": "partial", "definitions": "done"}


def test_a_term_the_law_defines_is_marked_where_it_holds(client: TestClient) -> None:
    body = _get(client, "/api/articles/STB-2026-56/1.1.4")
    (span,) = body["term_spans"]
    assert span["term"] == "slachtoffer"
    assert span["definition_ref"] == "stb_2026_56_1_5_1:a:slachtoffer"
    (definition,) = body["definitions"]
    assert definition["text"] == "het directe en het indirecte slachtoffer"
    assert body["enrichment"] == {"references": "done", "definitions": "done"}
    terms = {
        s["term"]
        for s in _get(client, "/api/articles/STB-2026-56/1.11.2")["term_spans"]
    }
    assert {"herstelrecht", "mediation", "slachtoffer"} <= terms
    listed = _get(client, "/api/instruments/wet_stb_2026_56/definitions")
    assert len(listed["definitions"]) == 8


def test_the_law_says_what_the_pipeline_made_of_it(client: TestClient) -> None:
    law = _get(client, "/api/instruments/wet_stb_2026_56")
    assert law["enrichment"] == {"references": "partial", "definitions": "done"}
    assert _get(client, "/api/articles/STB-2026-56/2.8.6")["enrichment"] == {
        "references": "done",
        "definitions": "done",
    }
    assert _get(client, f"/api/instruments/{SR}")["enrichment"] is None
