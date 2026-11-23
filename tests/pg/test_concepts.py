"""The block of a concept on a real PostgreSQL: its articles, and the judgments and papers
that cite any of them, each counted once; an article the data does not hold is named."""

from __future__ import annotations

from typing import Any

from lawgraph.api.schemas.concepts import ConceptResponse
from lawgraph.commands.curated import concept_article_notes
from lawgraph.core.concept_articles import Concept
from lawgraph.db import GraphStore, version_cache
from lawgraph.db.queries.concepts import CONCEPT_JUDGMENTS, concept_overview
from tests.asserts import assert_status

CONCEPT = Concept(
    key="toetsing",
    name="Toetsing van wetten",
    articles=("BWBR0001840/93", "BWBR0001840/120", "BWBR0001840/999"),
    explanation_label="Rijksoverheid",
    explanation_url="https://www.rijksoverheid.nl/onderwerpen/grondwet-en-statuut",
)
A93, A120 = "articles/bwbr0001840_93", "articles/bwbr0001840_120"


def _node(key: str, type_: str, **props: Any) -> dict[str, Any]:
    return {"key": key, "type": type_, "labels": [], "props": props}


def _edge(from_id: str, to_id: str, relation: str = "REFERS_TO") -> dict[str, Any]:
    key = f"e_{from_id.rsplit('/', 1)[1]}_{to_id.rsplit('/', 1)[1]}"
    return {"key": key, "from_id": from_id, "to_id": to_id, "relation": relation,
            "meta": {"mentions": [{"leden": [], "snippet": "…"}]}}  # fmt: skip


def _seed(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            _node("bwbr0001840_93", "article", bwb_id="BWBR0001840",
                  article_number="93", text="Bepalingen van verdragen hebben kracht."),
            _node("bwbr0001840_120", "article", bwb_id="BWBR0001840",
                  article_number="120", text="De rechter treedt niet in de beoordeling."),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            _node(f"j{i}", "judgment", ecli=f"ECLI:NL:RBDHA:2025:{i}",
                  date_eff=f"2025-0{i}-01", tier="rechtbank", court_code="RBDHA")
            for i in range(1, 8)
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "documents",
        [
            _node("d1", "document", kind="Memorie van toelichting", title="MvT",
                  date="2024-01-01", source="tk", dossier_number="36000", sequence=3),
            _node("d2", "document", kind="Motie", title="Motie", date="2025-01-01",
                  source="tk"),
            _node("d3", "document", kind="Brief", title="Brief", date="2026-01-01",
                  source="tk"),
        ],
    )  # fmt: skip
    edges = [_edge("judgments/j1", A93), _edge("judgments/j1", A120)]
    edges += [_edge(f"judgments/j{i}", A120) for i in range(2, 8)]
    edges += [
        _edge("documents/d1", A93, "EXPLAINS"),
        _edge("documents/d1", A120, "EXPLAINS"),
        _edge("documents/d2", A120),
        _edge(A93, "documents/d3"),
    ]
    store.bulk_insert_or_update_edges(edges)


def test_a_concept_counts_each_judgment_and_paper_once(store: GraphStore) -> None:
    _seed(store)
    version_cache.clear()

    answer = ConceptResponse.of(CONCEPT, concept_overview(store, CONCEPT.article_ids))

    assert [
        (a.display_name is not None, a.id, a.judgment_total) for a in answer.articles
    ] == [
        (True, A93, 1),
        (True, A120, 7),
    ]
    assert answer.articles[1].path == "/wetten/BWBR0001840/artikel/120"
    assert answer.articles[1].opening == "De rechter treedt niet in de beoordeling."
    assert answer.missing == ["BWBR0001840/999"]
    # j1 cites both: one judgment
    assert answer.judgment_total == 7
    assert len(answer.judgments) == CONCEPT_JUDGMENTS
    assert [j.judgment.key for j in answer.judgments] == ["j7", "j6", "j5", "j4", "j3"]
    assert answer.judgments[0].article_ids == [A120]
    # d1 is joined to both, d3 the other way round
    assert answer.document_total == 3
    assert [(d.document.key, d.article_ids) for d in answer.documents] == [
        ("d3", [A93]),
        ("d2", [A120]),
    ]
    assert answer.explanation is not None
    assert answer.explanation.label == "Rijksoverheid"


def test_the_oldest_judgment_lists_the_articles_it_cites(store: GraphStore) -> None:
    _seed(store)
    version_cache.clear()

    overview = concept_overview(store, (A93, A120))
    everyone = {j["judgment"]["key"] for j in overview["judgments"]}

    assert "j1" not in everyone
    assert overview["judgment_counts"] == {A93: 1, A120: 7}


def test_the_routes_give_a_concept_and_the_concepts_of_an_article(
    store: GraphStore, api: Any
) -> None:
    _seed(store)
    version_cache.clear()

    detail = api.get("/api/articles/BWBR0001840/120")
    concept = api.get("/api/concepts/toetsing-van-wetten")

    assert_status(detail, 200)
    assert detail.json()["concepts"] == [
        {"key": "toetsing-van-wetten", "name": "Toetsing van wetten"}
    ]
    assert_status(concept, 200)
    body = concept.json()
    assert [a["id"] for a in body["articles"]] == [A93, A120]
    assert body["missing"] == ["BWBR0001840/94"]
    assert body["judgment_total"] == 7
    assert_status(api.get("/api/concepts/onbekend"), 404)


def test_check_notes_an_article_of_a_block_the_graph_does_not_have(
    store: GraphStore,
) -> None:
    _seed(store)

    notes = concept_article_notes(store)

    assert (
        "concept-articles: toetsing-van-wetten: no article BWBR0001840/94 in the graph"
        in notes
    )
    assert not [n for n in notes if "BWBR0001840/120" in n], notes


def test_the_lists_count_as_the_block_does_and_page(
    store: GraphStore, api: Any
) -> None:
    _seed(store)
    version_cache.clear()
    base = "/api/concepts/toetsing-van-wetten"
    block = api.get(base).json()

    first = api.get(f"{base}/judgments?limit=3").json()
    rest = api.get(f"{base}/judgments?limit=3&offset=3").json()
    oldest = api.get(f"{base}/judgments?limit=1&offset=6").json()
    papers = api.get(f"{base}/documents?limit=2").json()
    last = api.get(f"{base}/documents?limit=2&offset=2").json()

    assert first["total"] == rest["total"] == block["judgment_total"] == 7
    assert [i["judgment"]["key"] for i in first["items"]] == ["j7", "j6", "j5"]
    assert [i["judgment"]["key"] for i in rest["items"]] == ["j4", "j3", "j2"]
    assert block["judgments"] == first["items"] + rest["items"][:2]
    # j1 cites both articles
    assert oldest["items"][0]["article_ids"] == sorted([A93, A120])
    assert papers["total"] == last["total"] == block["document_total"] == 3
    assert [d["document"]["key"] for d in papers["items"]] == ["d3", "d2"]
    assert block["documents"] == papers["items"]
    assert [d["article_ids"] for d in last["items"]] == [sorted([A93, A120])]


def test_the_judgments_sort_by_citation_count(store: GraphStore, api: Any) -> None:
    _seed(store)
    store.bulk_insert_or_update_nodes(
        "judgments",
        [_node("j2", "judgment", ecli="ECLI:NL:RBDHA:2025:2", date_eff="2025-02-01",
               tier="rechtbank", court_code="RBDHA", inbound_citation_count=9)],
    )  # fmt: skip
    version_cache.clear()

    cited = api.get("/api/concepts/toetsing-van-wetten/judgments?sort=citation_count")

    assert_status(cited, 200)
    keys = [i["judgment"]["key"] for i in cited.json()["items"]]
    assert keys[:3] == ["j2", "j7", "j6"]
    assert cited.json()["total"] == 7


def test_the_lists_of_an_unknown_concept_are_404(api: Any) -> None:
    assert_status(api.get("/api/concepts/onbekend/judgments"), 404)
    assert_status(api.get("/api/concepts/onbekend/documents"), 404)


def test_the_judgments_filter_by_court_tier_and_year(
    store: GraphStore, api: Any
) -> None:
    _seed(store)
    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            _node("j2", "judgment", ecli="ECLI:NL:HR:2024:2", date_eff="2024-02-01",
                  tier="hoge_raad", court_code="HR"),
            _node("j3", "judgment", ecli="ECLI:NL:RBDHA:2024:3", date_eff="2024-03-01",
                  tier="rechtbank", court_code="RBDHA"),
        ],
    )  # fmt: skip
    version_cache.clear()
    base = "/api/concepts/toetsing-van-wetten/judgments"

    court = api.get(f"{base}?court=hr").json()
    tier = api.get(f"{base}?tier=hoge_raad&tier=gerechtshof").json()
    year = api.get(f"{base}?year=2024").json()
    both = api.get(f"{base}?year=2024&court=RBDHA").json()

    assert (court["total"], [i["judgment"]["key"] for i in court["items"]]) == (
        1,
        ["j2"],
    )
    assert tier["total"] == 1
    assert [i["judgment"]["key"] for i in year["items"]] == ["j3", "j2"]
    # each facet counts the judgments under the other filters, not its own
    assert year["facets"]["year"] == [
        {"value": "2024", "count": 2},
        {"value": "2025", "count": 5},
    ]
    assert year["facets"]["tier"] == [
        {"value": "hoge_raad", "count": 1},
        {"value": "rechtbank", "count": 1},
    ]
    assert both["total"] == 1
    assert both["facets"]["year"] == [
        {"value": "2024", "count": 1},
        {"value": "2025", "count": 5},
    ]
    assert_status(api.get(f"{base}?year=24"), 422)
    assert_status(api.get(f"{base}?tier=geen"), 422)


def test_the_papers_filter_by_year(store: GraphStore, api: Any) -> None:
    _seed(store)
    version_cache.clear()

    papers = api.get("/api/concepts/toetsing-van-wetten/documents?year=2025").json()

    assert papers["total"] == 1
    assert [d["document"]["key"] for d in papers["items"]] == ["d2"]
