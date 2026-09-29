"""The instrument within an article's detail (J21) has the counts ``semantic
graph-list-stats`` stores on it, not zeros: Boek 6 within its article 162."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    RELATION_PART_OF,
    RELATION_REFERS_TO,
)
from lawgraph.core.models import Node, NodeType
from lawgraph.db import ArangoStore, EdgeWriter, NodeWriter

BW6 = "BWBR0005289"


def _node(collection: str, node_type: NodeType, key: str, **props: Any) -> Node:
    return Node(collection=collection, type=node_type, key=key, labels=[], props=props)


def test_the_instrument_of_an_article_has_its_counts(database: str, cli: Any) -> None:
    store = ArangoStore()
    articles = ["162", "163"]
    with NodeWriter(store) as writer:
        writer.add_all(
            [
                _node(
                    COLLECTION_INSTRUMENTS,
                    NodeType.INSTRUMENT,
                    "bwbr0005289",
                    bwb_id=BW6,
                    citation_title="Burgerlijk Wetboek Boek 6",
                    display_name="Burgerlijk Wetboek Boek 6",
                    jurisdiction="nl",
                ),
                *(
                    _node(
                        COLLECTION_ARTICLES,
                        NodeType.ARTICLE,
                        f"bwbr0005289_{number}",
                        bwb_id=BW6,
                        article_number=number,
                    )
                    for number in articles
                ),
                _node(
                    COLLECTION_JUDGMENTS,
                    NodeType.JUDGMENT,
                    "ecli_nl_hr_2020_1",
                    ecli="ECLI:NL:HR:2020:1",
                ),
            ]
        )
    with EdgeWriter(store, what=None) as edges:
        for number in articles:
            edges.add(
                f"{COLLECTION_ARTICLES}/bwbr0005289_{number}",
                f"{COLLECTION_INSTRUMENTS}/bwbr0005289",
                RELATION_PART_OF,
                source="t",
            )
        edges.add(
            f"{COLLECTION_JUDGMENTS}/ecli_nl_hr_2020_1",
            f"{COLLECTION_ARTICLES}/bwbr0005289_162",
            RELATION_REFERS_TO,
            source="t",
        )
    cli("semantic", "graph-list-stats")
    app.dependency_overrides[get_store] = lambda: store
    try:
        response = TestClient(app).get(f"/api/articles/{BW6}/162")
    finally:
        app.dependency_overrides.pop(get_store, None)

    assert response.status_code == 200, response.text
    instrument = response.json()["instrument"]
    assert (instrument["article_count"], instrument["inbound_citation_count"]) == (2, 1)
