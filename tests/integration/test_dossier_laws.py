"""The laws of a dossier (J13): an instrument the dossier changes in several ways is one item
with each of its links, and the laws its title names are there even when the graph does not
hold them. Dossier 34372, "Wijziging van het Wetboek van Strafrecht en het Wetboek van
Strafvordering ...", amends and introduces articles of the Wetboek van Strafrecht; the
Wetboek van Strafvordering is not loaded.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_INSTRUMENTS,
    RELATION_AMENDS,
    RELATION_INTRODUCES,
    RELATION_PART_OF,
)
from lawgraph.core.models import Node, NodeType
from lawgraph.db import ArangoStore, EdgeWriter, NodeWriter

TITLE = (
    "Wijziging van het Wetboek van Strafrecht en het Wetboek van Strafvordering in "
    "verband met de modernisering van de strafrechtelijke aanpak"
)
LAW = f"{COLLECTION_INSTRUMENTS}/bwbr0001854"


def _node(collection: str, node_type: NodeType, key: str, **props: Any) -> Node:
    return Node(collection=collection, type=node_type, key=key, labels=[], props=props)


def _seed(store: ArangoStore) -> None:
    with NodeWriter(store) as writer:
        writer.add_all(
            [
                _node(
                    COLLECTION_DOSSIERS,
                    NodeType.DOSSIER,
                    "34372",
                    number="34372",
                    label="34372",
                    title=TITLE,
                ),
                _node(
                    COLLECTION_INSTRUMENTS,
                    NodeType.INSTRUMENT,
                    "bwbr0001854",
                    bwb_id="BWBR0001854",
                    citation_title="Wetboek van Strafrecht",
                    display_name="Wetboek van Strafrecht",
                    jurisdiction="nl",
                ),
                _node(
                    COLLECTION_ARTICLES,
                    NodeType.ARTICLE,
                    "bwbr0001854_41",
                    bwb_id="BWBR0001854",
                    article_number="41",
                ),
                _node(
                    COLLECTION_DOCUMENTS, NodeType.DOCUMENT, "bill", kind="Wetsvoorstel"
                ),
            ]
        )
    article = f"{COLLECTION_ARTICLES}/bwbr0001854_41"
    bill = f"{COLLECTION_DOCUMENTS}/bill"
    with EdgeWriter(store, what=None) as edges:
        edges.add(article, LAW, RELATION_PART_OF, source="t")
        edges.add(bill, f"{COLLECTION_DOSSIERS}/34372", RELATION_PART_OF, source="t")
        edges.add(bill, article, RELATION_AMENDS, source="t")
        edges.add(bill, LAW, RELATION_INTRODUCES, source="t")
        edges.add(bill, LAW, RELATION_AMENDS, source="t", status="voorgesteld")


def test_a_law_is_one_item_and_the_laws_of_the_title_are_named(database: str) -> None:
    store = ArangoStore()
    _seed(store)
    app.dependency_overrides[get_store] = lambda: store
    try:
        response = TestClient(app).get("/api/dossiers/34372")
    finally:
        app.dependency_overrides.pop(get_store, None)
    assert response.status_code == 200, response.text
    dossier = response.json()

    (law,) = dossier["instruments"]
    assert (law["bwb_id"], law["relation"], law["status"]) == (
        "BWBR0001854",
        "amends",
        "canoniek",
    )
    assert law["links"] == [
        {"relation": "amends", "status": "canoniek"},
        {"relation": "introduces", "status": "canoniek"},
        {"relation": "amends", "status": "voorgesteld"},
    ]
    assert dossier["laws_named"] == [
        {
            "name": "Wetboek van Strafrecht",
            "loaded": True,
            "key": "bwbr0001854",
            "bwb_id": "BWBR0001854",
        },
        {
            "name": "Wetboek van Strafvordering",
            "loaded": False,
            "key": None,
            "bwb_id": None,
        },
    ]
