"""Which article a reference of the BWB XML points at, and how sure its type is: the real
``semantic bwb`` and ``semantic bwb-relation-types`` and the API on their answer.

The link of the XML is written by hand beside the words and is sometimes wrong where the
words are not: "artikel 230m" linked to article 230, "Artikel 62 leden 2 en 3 van Boek 4"
to article 178 of Boek 4. The words count; an edge an earlier run made to the linked
article goes.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_INSTRUMENTS,
    RELATION_REFERS_TO,
)
from lawgraph.core.models import make_node_key
from lawgraph.db import ArangoStore
from lawgraph.db.edges import make_edge_doc

BW4, BW6, BW7 = "BWBR0002761", "BWBR0005289", "BWBR0005290"
SOURCE = "bwb-article-references"
TEXT_178 = (
    "1. Een schenking is vernietigbaar.\n"
    "3. Artikel 62 leden 2 en 3 van Boek 4 is van overeenkomstige toepassing."
)
TEXT_230N = (
    "1. Aan de in artikel 230m lid 1, onderdelen h, i en j, bedoelde verplichtingen kan "
    "worden voldaan door verstrekking van modelinstructies."
)


def _ref(text: str, needle: str, bwb_id: str, article: str) -> dict[str, Any]:
    start = text.index(needle)
    return {
        "kind": "extref" if bwb_id == BW4 else "intref",
        "bwb_id": bwb_id,
        "article": article,
        "doc": f"jci1.3:c:{bwb_id}&artikel={article}",
        "text": needle,
        "start": start,
        "end": start + len(needle),
    }


def _put(store: ArangoStore, collection: str, key: str, **props: Any) -> None:
    doc = {"_key": key, "type": collection.rstrip("s"), "labels": [], "props": props}
    store.bulk_insert_or_update_nodes(collection, [doc])


def _article(store: ArangoStore, law: str, number: str, text: str = "", **more: Any):
    _put(
        store,
        COLLECTION_ARTICLES,
        make_node_key(law, number),
        bwb_id=law,
        article_number=number,
        text=text or f"Tekst van artikel {number}.",
        **more,
    )


@pytest.fixture()
def client(database: str, cli: Any) -> Iterator[tuple[TestClient, ArangoStore]]:
    store = ArangoStore()
    for law, title in ((BW4, "Boek 4"), (BW6, "Boek 6"), (BW7, "Boek 7")):
        _put(
            store,
            COLLECTION_INSTRUMENTS,
            make_node_key(law),
            bwb_id=law,
            title=f"Burgerlijk Wetboek {title}",
        )
    for law, number in ((BW4, "62"), (BW4, "178"), (BW6, "230"), (BW6, "230m")):
        _article(store, law, number)
    _article(
        store,
        BW7,
        "178",
        TEXT_178,
        references=[
            _ref(TEXT_178, "Artikel 62 leden 2 en 3 van Boek 4", BW4, "178"),
        ],
    )
    _article(
        store,
        BW6,
        "230n",
        TEXT_230N,
        references=[
            _ref(TEXT_230N, "artikel 230m lid 1, onderdelen h, i en j", BW6, "230"),
        ],
    )
    # the edge an earlier run made to the article the link points at
    store.bulk_insert_or_update_edges(
        [
            make_edge_doc(
                f"articles/{make_node_key(BW7, '178')}",
                f"articles/{make_node_key(BW4, '178')}",
                RELATION_REFERS_TO,
                source=SOURCE,
                confidence=1.0,
            )
        ]
    )
    cli("semantic", "bwb")
    cli("semantic", "bwb-relation-types")
    app.dependency_overrides[get_store] = lambda: store
    try:
        yield TestClient(app), store
    finally:
        app.dependency_overrides.clear()


def _targets(store: ArangoStore, law: str, number: str) -> list[dict[str, Any]]:
    return list(
        store.query(
            "FOR e IN edges FILTER e._from == @a AND e.relation == @r "
            "RETURN {to: PARSE_IDENTIFIER(e._to).key, linked: e.meta.linked_article}",
            {"a": f"articles/{make_node_key(law, number)}", "r": RELATION_REFERS_TO},
        )
    )


def test_the_words_of_a_reference_win_over_its_link(
    client: tuple[TestClient, ArangoStore],
) -> None:
    _, store = client
    assert _targets(store, BW7, "178") == [
        {"to": "bwbr0002761_62", "linked": "bwbr0002761_178"}
    ]
    assert _targets(store, BW6, "230n") == [
        {"to": "bwbr0005289_230m", "linked": "bwbr0005289_230"}
    ]


def test_a_type_from_a_pattern_is_not_certain_and_says_what_it_rests_on(
    client: tuple[TestClient, ArangoStore],
) -> None:
    api, _ = client
    response = api.get("/api/relationships/search", params={"law": BW6})
    assert response.status_code == 200
    (row,) = response.json()["relationships"]
    assert row["target_article"]["article_number"] == "230m"
    assert row["semantic_type"] == "definitional_reference"
    assert row["confidence"] == 1.0  # the reference itself is certain
    assert 0 < row["semantic_confidence"] < 1
    assert row["semantic_pattern"] == "definitional_reference_inverted_adjacent"
    assert "bedoelde" in row["explanation"]
