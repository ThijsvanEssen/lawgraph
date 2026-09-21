"""The instrument routes for a BWB regulation, an EU act and a treaty, on a real graph:
detail, the sub-routes of an EU act, and the links to EU acts and to international law."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.api.queries.instrument_links import get_international_links
from lawgraph.api.queries.instrument_scope import (
    resolve_instrument,
    scope_of,
    scope_of_node,
)
from lawgraph.api.queries.instruments import get_articles
from lawgraph.config.constants import (
    EDGE_SOURCE_BWB_IMPLEMENTS,
    RELATION_IMPLEMENTS,
    RELATION_PART_OF,
    RELATION_REFERS_TO,
)
from lawgraph.db import ArangoStore, make_edge_doc

REGULATION = "BWBR0009001"
OTHER_REGULATION = "BWBR0009002"
DIRECTIVE = "32016L0680"
TREATY = "BWBV0009001"


def _node(collection: str, key: str, **props: Any) -> dict[str, Any]:
    labels = props.pop("labels", [])
    return {"_key": key, "type": collection[:-1], "labels": labels, "props": props}


def _seed(store: ArangoStore) -> None:
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _node(
                "instruments",
                "bwbr0009001",
                bwb_id=REGULATION,
                title="Wet politiegegevens",
                citation_title="Wpg",
                kind="wet",
                jurisdiction="nl",
                source="bwb",
                article_count=2,
                date_in_force="2018-01-01",
            ),
            _node(
                "instruments",
                "bwbr0009002",
                bwb_id=OTHER_REGULATION,
                title="Besluit politiegegevens",
                kind="amvb",
                jurisdiction="nl",
            ),
            _node(
                "instruments",
                "32016l0680",
                celex=DIRECTIVE,
                title="Richtlijn (EU) 2016/680",
                citation_title="Richtlijn 2016/680/EU",
                jurisdiction="eu",
                source="eurlex",
                article_count=1,
                labels=["EU"],
            ),
            _node(
                "instruments",
                "bwbv0009001",
                bwb_id=TREATY,
                title="Verdrag inzake gegevens",
                kind="verdrag",
                jurisdiction="nl",
            ),
            _node(
                "instruments",
                "echr_convention",
                bwb_id="ECHR-CONVENTION",
                title="EVRM",
                kind="verdrag",
                jurisdiction="eu",
                labels=["ECHR", "Convention"],
            ),
            _node(
                "instruments", "verdrag_77", title="Losse verdrag", jurisdiction="int"
            ),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            _node("articles", "bwbr0009001_1", bwb_id=REGULATION, article_number="1"),
            _node("articles", "bwbr0009001_2", bwb_id=REGULATION, article_number="2"),
            _node(
                "articles", "bwbr0009002_1", bwb_id=OTHER_REGULATION, article_number="1"
            ),
            _node("articles", "32016l0680_1", celex=DIRECTIVE, article_number="1"),
            _node("articles", "32016l0680_10", celex=DIRECTIVE, article_number="10"),
            _node("articles", "bwbv0009001_5", bwb_id=TREATY, article_number="5"),
            _node(
                "articles",
                "echr_convention_8",
                bwb_id="ECHR-CONVENTION",
                article_number="8",
            ),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            _node(
                "judgments",
                "echr_001_1",
                source="echr",
                ecli="ECLI:CE:ECHR:2010:1",
                date="2010-01-01",
            ),
            _node(
                "judgments",
                "echr_001_2",
                source="echr",
                ecli="ECLI:CE:ECHR:2020:2",
                date="2020-01-01",
            ),
            _node(
                "judgments",
                "ecli_nl_hr_2020_1",
                source="rechtspraak",
                ecli="ECLI:NL:HR:2020:1",
            ),
        ],
    )
    refers = RELATION_REFERS_TO
    edges = [
        make_edge_doc(
            "instruments/bwbr0009001",
            "instruments/32016l0680",
            RELATION_IMPLEMENTS,
            source=EDGE_SOURCE_BWB_IMPLEMENTS,
            confidence=0.75,
            meta={"celex": DIRECTIVE},
        ),
        make_edge_doc(
            "instruments/bwbr0009002",
            "instruments/32016l0680",
            RELATION_IMPLEMENTS,
            source=EDGE_SOURCE_BWB_IMPLEMENTS,
            confidence=0.75,
            meta={"celex": DIRECTIVE},
        ),
        make_edge_doc(
            "articles/32016l0680_1", "instruments/32016l0680", RELATION_PART_OF
        ),
        # a national article names a treaty article; another names the ECHR Convention
        make_edge_doc(
            "articles/bwbr0009001_1",
            "articles/bwbv0009001_5",
            refers,
            source="bwb-article-references",
            confidence=1.0,
            meta={"raw_match": "artikel 5 van het Verdrag", "snippet": "zie artikel 5"},
        ),
        # a national article refers to an article of the directive
        make_edge_doc(
            "articles/bwbr0009001_2",
            "articles/32016l0680_1",
            refers,
            source="eu-article-linker",
            confidence=0.85,
        ),
        # ECHR judgments: to a Convention article, and to the regulation as a whole
        make_edge_doc(
            "judgments/echr_001_1",
            "articles/echr_convention_8",
            refers,
            source="echr-citation-linker",
            confidence=0.95,
            meta={"article": "8", "instrument": "EVRM"},
        ),
        make_edge_doc(
            "judgments/echr_001_2",
            "articles/echr_convention_8",
            refers,
            source="echr-citation-linker",
            confidence=0.95,
            meta={"article": "8", "instrument": "EVRM"},
        ),
        make_edge_doc(
            "judgments/echr_001_2",
            "instruments/bwbr0009001",
            refers,
            source="echr-citation-linker",
            confidence=0.8,
            meta={"match_type": "bwb_text_scan"},
        ),
        # a Dutch judgment: to the directive's article, not an international link
        make_edge_doc(
            "judgments/ecli_nl_hr_2020_1",
            "articles/32016l0680_1",
            refers,
            source="rechtspraak-article-linker",
            confidence=0.9,
        ),
        make_edge_doc(
            "judgments/ecli_nl_hr_2020_1",
            "articles/bwbr0009001_1",
            refers,
            source="rechtspraak-article-linker",
            confidence=0.9,
        ),
    ]
    store.bulk_insert_or_update_edges(edges)


@pytest.fixture()
def store(database: str) -> Iterator[ArangoStore]:
    store = ArangoStore()
    _seed(store)
    app.dependency_overrides[get_store] = lambda: store
    yield store
    app.dependency_overrides.pop(get_store, None)


def test_the_resolver_names_an_instrument_by_bwb_id_celex_or_key(
    store: ArangoStore,
) -> None:
    for identifier, key in [
        (REGULATION, "bwbr0009001"),
        ("bwbr0009001", "bwbr0009001"),
        (DIRECTIVE, "32016l0680"),
        ("32016l0680", "32016l0680"),
        ("ECHR-CONVENTION", "echr_convention"),
        ("echr_convention", "echr_convention"),
        ("verdrag_77", "verdrag_77"),
    ]:
        found = resolve_instrument(store, identifier)
        assert found is not None and found["_key"] == key, identifier
    assert resolve_instrument(store, "BWBR0000000") is None
    assert resolve_instrument(store, "32099L9999") is None

    directive = resolve_instrument(store, DIRECTIVE)
    assert directive is not None
    assert scope_of_node(directive) == scope_of(DIRECTIVE)
    loose = resolve_instrument(store, "verdrag_77")
    assert loose is not None and scope_of_node(loose) is None


def test_the_detail_of_a_regulation_an_eu_act_and_an_unknown_instrument(
    store: ArangoStore,
) -> None:
    client = TestClient(app)
    regulation = client.get(f"/api/instruments/{REGULATION}").json()
    assert regulation["id"] == "instruments/bwbr0009001"
    assert (regulation["bwb_id"], regulation["celex"]) == (REGULATION, None)
    assert regulation["kind"] == "wet" and regulation["date_in_force"] == "2018-01-01"

    directive = client.get(f"/api/instruments/{DIRECTIVE.lower()}").json()
    assert (directive["celex"], directive["jurisdiction"]) == (DIRECTIVE, "eu")
    assert directive["labels"] == ["EU"]

    assert client.get("/api/instruments/BWBR0000000").status_code == 404
    assert client.get("/api/instruments/BWBR0000000/eu-links").status_code == 404


def test_the_sub_routes_answer_for_an_eu_act(store: ArangoStore) -> None:
    client = TestClient(app)

    articles = client.get(f"/api/instruments/{DIRECTIVE}/articles").json()
    assert articles["bwb_id"] == DIRECTIVE and articles["total"] == 2
    assert [a["article_number"] for a in articles["items"]] == ["1", "10"]
    assert articles["items"][0]["celex"] == DIRECTIVE

    citations = client.get(f"/api/instruments/{DIRECTIVE}/citations").json()
    assert citations["article_count"] == 2
    edges = {(e["from"], e["direction"]) for e in citations["edges"]}
    assert ("judgments/ecli_nl_hr_2020_1", "in") in edges
    assert ("articles/bwbr0009001_2", "in") in edges

    judgments = client.get(f"/api/instruments/{DIRECTIVE}/judgments").json()
    assert judgments["total"] == 1
    assert judgments["items"][0]["cited_articles"][0]["key"] == "32016l0680_1"

    related = client.get(f"/api/instruments/{DIRECTIVE}/related-instruments").json()
    assert [(i["bwb_id"], i["inbound_count"]) for i in related["items"]] == [
        (REGULATION, 1)
    ]

    for suffix in ("dossiers", "amended-by", "cross-law-dependencies"):
        answer = client.get(f"/api/instruments/{DIRECTIVE}/{suffix}")
        assert answer.status_code == 200, suffix

    # a regulation still reads its own articles and judgments
    assert client.get(f"/api/instruments/{REGULATION}/articles").json()["total"] == 2
    assert client.get(f"/api/instruments/{REGULATION}/judgments").json()["total"] == 1


def test_eu_links_between_a_regulation_and_an_eu_act(store: ArangoStore) -> None:
    client = TestClient(app)

    up = client.get(f"/api/instruments/{REGULATION}/eu-links").json()
    assert up["instrument"]["bwb_id"] == REGULATION
    assert up["implemented_by"] == [] and up["implemented_by_total"] == 0
    assert up["implements_total"] == 1
    link = up["implements"][0]
    assert link["instrument"]["celex"] == DIRECTIVE
    assert link["instrument"]["key"] == "32016l0680"
    assert (link["relation"], link["confidence"]) == ("IMPLEMENTS", 0.75)
    assert link["basis"] == "celex_named_in_text"
    assert link["source"] == "bwb-implements-directive"
    assert link["meta"] == {"celex": DIRECTIVE}
    assert "articles" not in link

    down = client.get(f"/api/instruments/{DIRECTIVE}/eu-links?limit=1").json()
    assert down["implements"] == []
    assert down["implemented_by_total"] == 2 and len(down["implemented_by"]) == 1
    assert down["implemented_by"][0]["instrument"]["bwb_id"] == REGULATION


def test_international_links_hold_treaties_and_echr_judgments(
    store: ArangoStore,
) -> None:
    client = TestClient(app)

    regulation = client.get(f"/api/instruments/{REGULATION}/eu-links").json()
    assert regulation["international_total"] == 2
    treaty, echr = regulation["international"]  # treaties first
    assert treaty["kind"] == "treaty" and treaty["judgment"] is None
    assert treaty["instrument"]["bwb_id"] == TREATY
    assert treaty["own_article"]["key"] == "bwbr0009001_1"
    assert treaty["counterpart_article"]["article_number"] == "5"
    assert treaty["confidence"] == 1.0
    assert treaty["meta"]["raw_match"] == "artikel 5 van het Verdrag"
    assert echr["kind"] == "echr_judgment" and echr["instrument"] is None
    assert echr["judgment"]["ecli"] == "ECLI:CE:ECHR:2020:2"
    assert echr["own_article"] is None  # the regulation as a whole
    assert echr["meta"] == {"match_type": "bwb_text_scan"}

    # the Dutch judgment that cites an article of the regulation is not an ECHR link
    eclis = {
        i["judgment"]["ecli"] for i in regulation["international"] if i["judgment"]
    }
    assert eclis == {"ECLI:CE:ECHR:2020:2"}

    convention = client.get("/api/instruments/ECHR-CONVENTION/eu-links").json()
    assert convention["international_total"] == 2
    assert [i["judgment"]["ecli"] for i in convention["international"]] == [
        "ECLI:CE:ECHR:2020:2",  # same confidence: newest first
        "ECLI:CE:ECHR:2010:1",
    ]
    assert convention["international"][0]["own_article"]["article_number"] == "8"
    assert convention["international"][0]["meta"]["instrument"] == "EVRM"

    page = client.get("/api/instruments/echr_convention/eu-links?limit=1").json()
    assert len(page["international"]) == 1 and page["international_total"] == 2

    # no article of an EU act refers to a treaty, and no ECHR judgment to it
    directive = client.get(f"/api/instruments/{DIRECTIVE}/eu-links").json()
    assert directive["international"] == [] and directive["international_total"] == 0

    # an instrument without articles has an empty answer, not an error
    loose = client.get("/api/instruments/verdrag_77/eu-links").json()
    assert loose["international"] == [] and loose["implements"] == []


def test_the_articles_of_an_instrument_are_read_through_an_index(
    store: ArangoStore,
) -> None:
    """Both identifying props are indexed: no scan of the articles, for either kind.

    The compound indexes on (bwb_id, article_number) are sparse and cannot answer a filter
    on the first field alone; with a few thousand articles around, that was a full scan.
    """
    fillers = [
        _node(
            "articles",
            f"bwbr{9100000 + n // 20}_{n % 20}",
            bwb_id=f"BWBR{9100000 + n // 20}",
            article_number=str(n % 20),
        )
        for n in range(3000)
    ] + [
        _node(
            "articles",
            f"3{2000 + n // 10}l{n % 10:04d}_1",
            celex=f"3{2000 + n // 10}L{n % 10:04d}",
            article_number="1",
        )
        for n in range(2000)
    ]
    store.bulk_insert_or_update_nodes("articles", fillers)
    asked: list[tuple[str, dict[str, Any]]] = []
    run = store.query

    def recording(aql: str, bind_vars: dict[str, Any] | None = None, **kw: Any) -> Any:
        asked.append((aql, bind_vars or {}))
        return run(aql, bind_vars, **kw)

    store.query = recording  # type: ignore[method-assign]
    for identifier in (REGULATION, DIRECTIVE):
        get_articles(store, identifier)
        scope = scope_of(identifier)
        get_international_links(store, "instruments/x", scope)

    assert len(asked) == 4
    for aql, bind_vars in asked:
        nodes = store.db.aql.explain(aql, bind_vars=bind_vars)["nodes"]
        scanned = [n for n in nodes if n["type"] == "EnumerateCollectionNode"]
        assert all(n["collection"] != "articles" for n in scanned), aql
