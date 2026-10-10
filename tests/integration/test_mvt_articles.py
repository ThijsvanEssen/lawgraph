"""The sections of memoranda linked to articles, through the real pipelines on a real database.

``semantic tk-mvt`` and ``semantic tk-mvt-articles`` write to the same edge (one per document and
target): the result must not depend on which ran first or how often, and the API reads it back.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    RELATION_AMENDS,
    RELATION_INTRODUCES,
    RELATION_LEGISLATED_IN,
    RELATION_PART_OF,
)
from lawgraph.core.bwb_xml import article_version_key
from lawgraph.core.kamerstuk_xml import parse_kamerstuk
from lawgraph.core.models import make_node_key
from lawgraph.core.mvt_articles import (
    CONFIDENCE_OF_MATCH,
    MATCH_BODY_NAMED_LAW,
    MATCH_OWN_NUMBER,
)
from lawgraph.db import GraphStore, make_edge_doc
from lawgraph.pipelines.semantic.tk_mvt import (
    DOSSIER_CONFIDENCE,
    SEMANTIC_SOURCE,
    SEMANTIC_SOURCE_SECTIONS,
)
from tests.integration.seed import FIXTURES

KLIMAATFONDS = "BWBR0044234"  # amended by dossier 36750
NEW_LAW = "BWBR0099001"  # made by dossier 36100
BUDGET_LAW = "BWBR0099002"  # amended by the budget paper of dossier 36200


@pytest.fixture(autouse=True)
def _clear_override() -> Iterator[None]:
    yield
    app.dependency_overrides.pop(get_store, None)


def _node(
    store: GraphStore, collection: str, key: str, node_type: str, **props: Any
) -> str:
    store.bulk_insert_or_update_nodes(
        collection, [{"_key": key, "type": node_type, "labels": [], "props": props}]
    )
    return f"{collection}/{key}"


def _edge(
    store: GraphStore, from_id: str, to_id: str, relation: str, **meta: Any
) -> None:
    doc = make_edge_doc(from_id, to_id, relation, source="test", meta=meta)
    store.bulk_insert_or_update_edges([doc])


def _article(store: GraphStore, bwb_id: str, number: str) -> tuple[str, str]:
    """An article and one version of it: ``(article id, version key)``."""
    stam = f"st{number}"
    article = _node(
        store,
        "articles",
        make_node_key(bwb_id, number),
        "article",
        bwb_id=bwb_id,
        article_number=number,
        stam_id=stam,
    )
    version = article_version_key(bwb_id, stam, "v1")
    _node(
        store,
        "article_versions",
        version,
        "article_version",
        bwb_id=bwb_id,
        article_number=number,
        stam_id=stam,
    )
    return article, version


def _law(store: GraphStore, bwb_id: str, title: str, **props: Any) -> str:
    return _node(
        store,
        "instruments",
        make_node_key(bwb_id),
        "instrument",
        bwb_id=bwb_id,
        title=title,
        citation_title=title,
        **props,
    )


class _Paper:
    """Text and sections of a memorandum made of headings and bodies."""

    def __init__(self) -> None:
        self.text = ""
        self.sections: list[dict[str, Any]] = []

    def article(self, number: str, body: str) -> None:
        heading = f"Artikel {number}"
        start = len(self.text) + (1 if self.text else 0)
        block = f"{heading}\n{body}"
        self.text += ("\n" if self.text else "") + block
        self.sections.append(
            {
                "id": f"s-{len(self.sections)}",
                "heading": heading,
                "level": 1,
                "parent": None,
                "kind": "article",
                "number": number,
                "number_scheme": "arabic",
                "article_refs": [{"number": number, "of": "self"}],
                "law": None,
                "char_start": start,
                "char_end": start + len(block),
            }
        )


def _memorandum(
    store: GraphStore,
    key: str,
    dossier: str,
    text: str,
    sections: list[dict[str, Any]],
    *,
    budget: bool = False,
) -> str:
    document = _node(
        store,
        "documents",
        key,
        "document",
        kind="Memorie van toelichting",
        title=f"Memorie van toelichting {key}",
        text=text,
        sections=sections,
        structure_quality="explicit",
        budget=budget,
    )
    _edge(store, document, f"dossiers/{dossier}", RELATION_PART_OF)
    return document


def _graph(store: GraphStore) -> dict[str, str]:
    """Three dossiers; returns the ids of what the assertions name."""
    ids: dict[str, str] = {}

    # 36750: a bill that changes the Tijdelijke wet Klimaatfonds (a real memorandum)
    _node(store, "dossiers", "36750", "dossier", number="36750")
    _law(store, KLIMAATFONDS, "Tijdelijke wet Klimaatfonds")
    publication = _node(
        store, "instruments", "stb_2025_1", "instrument", display_name="Stb. 2025, 1"
    )
    _edge(store, publication, "dossiers/36750", RELATION_LEGISLATED_IN)
    for number in ("2", "3"):
        article, version = _article(store, KLIMAATFONDS, number)
        _edge(store, publication, article, RELATION_AMENDS, article_version=version)
        ids[f"klimaat_{number}"] = f"article_versions/{version}"
    parsed = parse_kamerstuk((FIXTURES / "kst_36750_3.xml").read_text(encoding="utf-8"))
    ids["klimaat_doc"] = _memorandum(
        store, "mvt_36750", "36750", parsed.text, [s.as_dict() for s in parsed.sections]
    )

    # 36100: a new law; the publication introduces articles 1 and 2, article 3 has no change edge
    _node(store, "dossiers", "36100", "dossier", number="36100")
    law = _law(store, NEW_LAW, "Wet nieuw", dossier_numbers=[36100])
    _edge(store, law, "dossiers/36100", RELATION_LEGISLATED_IN)
    publication = _node(
        store, "instruments", "stb_2025_2", "instrument", display_name="Stb. 2025, 2"
    )
    _edge(store, publication, "dossiers/36100", RELATION_LEGISLATED_IN)
    for number in ("1", "2"):
        article, version = _article(store, NEW_LAW, number)
        _edge(store, publication, article, RELATION_INTRODUCES, article_version=version)
        ids[f"new_{number}"] = f"article_versions/{version}"
    ids["new_3"], _ = _article(store, NEW_LAW, "3")
    paper = _Paper()
    for number in ("1", "2", "3", "9"):
        paper.article(number, f"Toelichting op artikel {number}.")
    ids["new_doc"] = _memorandum(
        store, "mvt_36100", "36100", paper.text, paper.sections
    )

    # 36200: a budget paper: its numbered articles are policy articles
    _node(store, "dossiers", "36200", "dossier", number="36200")
    _law(store, BUDGET_LAW, "Begrotingswet")
    publication = _node(
        store, "instruments", "stb_2025_3", "instrument", display_name="Stb. 2025, 3"
    )
    _edge(store, publication, "dossiers/36200", RELATION_LEGISLATED_IN)
    article, version = _article(store, BUDGET_LAW, "2")
    _edge(store, publication, article, RELATION_AMENDS, article_version=version)
    ids["budget_2"] = f"article_versions/{version}"
    paper = _Paper()
    paper.article("2", "Toelichting op artikel 2 van de Begrotingswet.")
    ids["budget_doc"] = _memorandum(
        store, "mvt_36200", "36200", paper.text, paper.sections, budget=True
    )
    return ids


def _explains(store: GraphStore) -> dict[str, dict[str, Any]]:
    """Every EXPLAINS edge by key, without what differs between two builds (``created_at``)."""
    statement = """
    SELECT key, from_id AS "from", to_id AS "to", doc -> 'source' AS source,
           doc -> 'confidence' AS confidence, doc -> 'status' AS status,
           doc -> 'meta' AS meta
    FROM edges WHERE relation = 'EXPLAINS'
    """
    return {row["key"]: row for row in store.query(statement)}


def _revisions(store: GraphStore) -> dict[str, str]:
    """The row version of every edge: an upsert that changes nothing does not write."""
    rows = store.query("SELECT key, xmin::text AS rev FROM edges")
    return {row["key"]: row["rev"] for row in rows}


def _by_target(store: GraphStore, document: str) -> dict[str, dict[str, Any]]:
    return {e["to"]: e for e in _explains(store).values() if e["from"] == document}


def _check_the_result(store: GraphStore, ids: dict[str, str]) -> None:
    klimaat = _by_target(store, ids["klimaat_doc"])
    named = klimaat[ids["klimaat_2"]]
    assert (named["source"], named["confidence"]) == (
        SEMANTIC_SOURCE_SECTIONS,
        CONFIDENCE_OF_MATCH[MATCH_BODY_NAMED_LAW],
    )
    assert named["meta"]["match_type"] == "body_named_law"
    assert named["meta"]["changed"] is True
    assert named["meta"]["explanation"].endswith("het dossier wijzigt het artikel.")
    assert named["meta"]["heading"] == "Artikel I" and named["meta"]["section_anchor"]
    assert [s["section_anchor"] for s in named["meta"]["sections"]] == [
        named["meta"]["section_anchor"]
    ]
    # article 3 was changed and is not named: the dossier says it, at the dossier's confidence
    other = klimaat[ids["klimaat_3"]]
    assert (other["source"], other["confidence"]) == (
        SEMANTIC_SOURCE,
        DOSSIER_CONFIDENCE,
    )
    assert "section_anchor" not in other["meta"]

    new = _by_target(store, ids["new_doc"])
    for number in ("1", "2"):
        edge = new[ids[f"new_{number}"]]
        assert (edge["source"], edge["confidence"]) == (
            SEMANTIC_SOURCE_SECTIONS,
            CONFIDENCE_OF_MATCH[MATCH_OWN_NUMBER],
        )
        assert edge["meta"]["match_type"] == "own_number"
        assert edge["meta"]["heading"] == f"Artikel {number}"
    # the article no change edge names: an edge only the sections know of
    assert new[ids["new_3"]]["source"] == SEMANTIC_SOURCE_SECTIONS
    assert len(new) == 3  # "Artikel 9" is no article of the law

    budget = _by_target(store, ids["budget_doc"])
    assert {e["source"] for e in budget.values()} == {SEMANTIC_SOURCE}
    assert all("section_anchor" not in e["meta"] for e in budget.values())


def _run(cli: Any, *names: str) -> str:
    return "\n".join(cli("semantic", name).stderr for name in names)


def test_the_result_is_the_same_in_either_order_and_a_rerun_writes_nothing(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    ids = _graph(store)

    _run(cli, "tk-mvt")
    # before the sections: what the dossier says, claimed at half
    dossier_level = _explains(store)
    assert {e["confidence"] for e in dossier_level.values()} == {DOSSIER_CONFIDENCE}
    _run(cli, "tk-mvt-articles")
    first = _explains(store)
    _check_the_result(store, ids)
    # the edge of a section is the edge of the dossier, upgraded: no key is added but new_3
    assert set(first) - set(dossier_level) == {
        key for key, e in first.items() if e["to"] == ids["new_3"]
    }

    # the other way round: the edges are removed and both run again, sections first
    store.execute("DELETE FROM edges WHERE relation = 'EXPLAINS'")
    _run(cli, "tk-mvt-articles", "tk-mvt")
    assert _explains(store) == first
    _run(cli, "tk-mvt-articles", "tk-mvt", "tk-mvt-articles")
    assert _explains(store) == first

    # and a run of both over what is there writes nothing
    before = _revisions(store)
    again = _run(cli, "tk-mvt", "tk-mvt-articles")
    assert _revisions(store) == before
    assert not re.search(r"\d+ (created|updated)", again), again[-600:]
    assert re.search(r"Done in \S+: [\d,]+ unchanged", again), again[-600:]


def test_the_api_reads_the_passages_of_an_article_back(database: str, cli: Any) -> None:
    store = GraphStore()
    _graph(store)
    _run(cli, "tk-mvt", "tk-mvt-articles")
    app.dependency_overrides[get_store] = lambda: store
    client = TestClient(app)

    def passages(document: str, bwb_id: str, article: str) -> dict[str, Any]:
        response = client.get(
            f"/api/documents/{document}/passages",
            params={"bwb_id": bwb_id, "article": article},
        )
        assert response.status_code == 200
        return response.json()

    body = passages("mvt_36750", KLIMAATFONDS, "2")
    assert body["total"] == 1
    (passage,) = body["items"]
    assert (
        passage["heading"] == "Artikel I" and passage["match_type"] == "body_named_law"
    )
    assert passage["confidence"] == CONFIDENCE_OF_MATCH[MATCH_BODY_NAMED_LAW]
    assert passage["changed"] is True
    assert passage["explanation"].startswith("De tekst onder de kop 'Artikel I'")
    assert passage["text"].startswith("Artikel I\nDit wetsvoorstel beoogt artikel 2")
    assert passage["level"] == 2

    # an article the dossier changed and no section names, and one that is not in the graph
    assert passages("mvt_36750", KLIMAATFONDS, "3") == {"total": 0, "items": []}
    assert passages("mvt_36750", KLIMAATFONDS, "99") == {"total": 0, "items": []}

    # a new law: the article with a change edge (through its version) and the one without
    for number in ("1", "3"):
        body = passages("mvt_36100", NEW_LAW, number)
        assert [p["heading"] for p in body["items"]] == [f"Artikel {number}"]
        assert (
            body["items"][0]["text"]
            == f"Artikel {number}\nToelichting op artikel {number}."
        )
    assert passages("mvt_36100", NEW_LAW, "9")["total"] == 0
    assert passages("mvt_36200", BUDGET_LAW, "2")["total"] == 0

    assert (
        client.get(
            "/api/documents/nope/passages", params={"bwb_id": NEW_LAW, "article": "1"}
        ).status_code
        == 404
    )

    document = client.get("/api/documents/mvt_36750").json()
    assert [s["kind"] for s in document["sections"]].count("article") == 2
    assert all(s["char_end"] <= len(document["text"]) for s in document["sections"])


def test_the_reader_gets_the_passages_of_an_article(database: str, cli: Any) -> None:
    """``explanations``: per paper its passages with their text, for the article reader;
    what explains only the dossier is not there."""
    store = GraphStore()
    ids = _graph(store)
    _run(cli, "tk-mvt", "tk-mvt-articles")
    app.dependency_overrides[get_store] = lambda: store
    client = TestClient(app)

    def explanations(bwb_id: str, article: str) -> dict[str, Any]:
        response = client.get(f"/api/articles/{bwb_id}/{article}/explanations")
        assert response.status_code == 200
        return response.json()

    body = explanations(KLIMAATFONDS, "2")
    assert body["article_id"] == f"articles/{make_node_key(KLIMAATFONDS, '2')}"
    assert body["total"] == 1
    (item,) = body["items"]
    assert item["document"]["id"] == ids["klimaat_doc"]
    assert item["document"]["kind"] == "Memorie van toelichting"
    assert item["target"] == "article_version"
    assert item["target_id"] == ids["klimaat_2"]
    (passage,) = item["passages"]
    assert passage["heading"] == "Artikel I"
    assert passage["match_type"] == "body_named_law"
    assert passage["text"].startswith("Artikel I\nDit wetsvoorstel beoogt artikel 2")
    # the same passage as the memorandum's own route gives
    same = client.get(
        f"/api/documents/{item['document']['key']}/passages",
        params={"bwb_id": KLIMAATFONDS, "article": "2"},
    ).json()["items"]
    assert [item["passages"]] == [same]

    # a new law: through the version, and the article without a change edge itself
    for number, target in (("1", "article_version"), ("3", "article")):
        (item,) = explanations(NEW_LAW, number)["items"]
        assert item["target"] == target
        assert [p["text"] for p in item["passages"]] == [
            f"Artikel {number}\nToelichting op artikel {number}."
        ]

    # explained for the dossier only, a budget paper, and an unknown article: nothing
    empty = {"total": 0, "items": []}
    for bwb_id, number in ((KLIMAATFONDS, "3"), (BUDGET_LAW, "2"), (NEW_LAW, "99")):
        body = explanations(bwb_id, number)
        assert {"total": body["total"], "items": body["items"]} == empty


PROEF = "BWBR0099003"  # changed by dossier 36300, whose memorandum names onderdelen
_BILL_36300 = """VOORSTEL VAN WET
ARTIKEL I
Het Wetboek van Proef wordt als volgt gewijzigd:
A
In artikel 10, eerste lid, wordt «twee» vervangen door: drie.
B
Na artikel 20 worden twee artikelen ingevoegd, luidende:
Artikel 20a
Hij die proeft, wordt gestraft.
Artikel 20b
Hij die niet proeft, ook.
ARTIKEL II
Deze wet treedt in werking met ingang van de dag na de uitgifte."""


def _onderdelen_graph(store: GraphStore) -> dict[str, str]:
    """36300: a bill that changes a code, explained per onderdeel; 20b was left out by an
    amendment (no change edge)."""
    ids: dict[str, str] = {}
    _node(store, "dossiers", "36300", "dossier", number="36300")
    _law(store, PROEF, "Wetboek van Proef")
    publication = _node(
        store, "instruments", "stb_2025_4", "instrument", display_name="Stb. 2025, 4"
    )
    _edge(store, publication, "dossiers/36300", RELATION_LEGISLATED_IN)
    for number, relation in (("10", RELATION_AMENDS), ("20a", RELATION_INTRODUCES)):
        article, version = _article(store, PROEF, number)
        _edge(store, publication, article, relation, article_version=version)
        ids[number] = f"article_versions/{version}"
    ids["20b"], _ = _article(store, PROEF, "20b")
    bill = _node(
        store,
        "documents",
        "bill_36300",
        "document",
        kind="Voorstel van wet",
        date="2025-01-01",
        text=_BILL_36300,
    )
    _edge(store, bill, "dossiers/36300", RELATION_PART_OF)
    text, sections = "", []
    for heading, body in (
        ("Artikel I, onderdeel A", "De boete gaat omhoog."),
        ("Artikel I, onderdeel B", "Twee nieuwe delicten."),
        ("Artikel II", "De inwerkingtreding."),
    ):
        start = len(text) + (1 if text else 0)
        block = f"{heading}\n{body}"
        text += ("\n" if text else "") + block
        number = heading.split()[1].rstrip(",")
        sections.append(
            {
                "id": f"s-{len(sections)}",
                "heading": heading,
                "level": 1,
                "parent": None,
                "kind": "article",
                "number": number,
                "number_scheme": "roman",
                "article_refs": [{"number": number, "of": "self"}],
                "law": None,
                "char_start": start,
                "char_end": start + len(block),
            }
        )
    ids["doc"] = _memorandum(store, "mvt_36300", "36300", text, sections)
    return ids


def test_a_memorandum_per_onderdeel_explains_what_the_bill_says_it_changes(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    ids = _onderdelen_graph(store)

    _run(cli, "tk-mvt", "tk-mvt-articles")

    edges = _by_target(store, ids["doc"])
    for number, section in (("10", "s-0"), ("20a", "s-1")):
        meta = edges[ids[number]]["meta"]
        assert meta["section_anchor"] == section
        assert meta["match_type"] == "bill_part"
        assert meta["changed"] is True
    # what the bill inserted and the dossier did not change, and the bill's own articles
    assert ids["20b"] not in edges
    assert set(edges) == {ids["10"], ids["20a"]}

    # and the reader gets the onderdeel as the passage of the article
    app.dependency_overrides[get_store] = lambda: store
    body = TestClient(app).get(f"/api/articles/{PROEF}/20a/explanations").json()
    (item,) = body["items"]
    (passage,) = item["passages"]
    assert (passage["heading"], passage["match_type"]) == (
        "Artikel I, onderdeel B",
        "bill_part",
    )
    assert passage["text"] == "Artikel I, onderdeel B\nTwee nieuwe delicten."


def test_a_section_edge_the_code_no_longer_derives_goes_back_to_the_dossier(
    database: str, cli: Any
) -> None:
    """A full run replaces what it wrote before: a section edge it no longer finds becomes
    the dossier-level edge again when the dossier changed the article, and goes when not."""
    store = GraphStore()
    ids = _graph(store)
    _run(cli, "tk-mvt", "tk-mvt-articles")
    stale = {
        "section_anchor": "s-1",
        "sections": [{"section_anchor": "s-1", "heading": "Artikel I"}],
        "match_type": "body_named_law",
    }
    # what an earlier code wrote: 3 of the Klimaatfonds (changed, no section names it), and
    # an article of another dossier's law
    for target in (ids["klimaat_3"], ids["new_1"]):
        doc = make_edge_doc(
            ids["klimaat_doc"],
            target,
            "EXPLAINS",
            source=SEMANTIC_SOURCE_SECTIONS,
            confidence=0.65,
            meta=stale,
        )
        store.bulk_insert_or_update_edges([doc])
    assert ids["new_1"] in _by_target(store, ids["klimaat_doc"])

    _run(cli, "tk-mvt-articles")

    edges = _by_target(store, ids["klimaat_doc"])
    back = edges[ids["klimaat_3"]]
    assert (back["source"], back["confidence"]) == (SEMANTIC_SOURCE, DOSSIER_CONFIDENCE)
    assert not (back["meta"] or {}).get("sections")
    assert ids["new_1"] not in edges
    # what it still derives stays as it was
    assert edges[ids["klimaat_2"]]["source"] == SEMANTIC_SOURCE_SECTIONS
