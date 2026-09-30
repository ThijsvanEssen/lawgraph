"""A change in the Grondwet is made law in its second reading, whose memorandum only refers to
the papers of the first reading. The real query of ``semantic tk-mvt`` gives the memorandum of
the first reading what the second reading changed, once ``SECOND_READING_OF`` ties the two."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_INSTRUMENTS,
    RELATION_AMENDS,
    RELATION_LEGISLATED_IN,
    RELATION_PART_OF,
    RELATION_SECOND_READING_OF,
)
from lawgraph.core.models import Node, NodeType
from lawgraph.db import ArangoStore, EdgeWriter, NodeWriter
from lawgraph.db.queries.semantic import memorandum_targets

ARTICLE = f"{COLLECTION_ARTICLES}/bwbr0001840_13"
FIRST, SECOND = f"{COLLECTION_DOSSIERS}/35418", f"{COLLECTION_DOSSIERS}/35785"


def _node(collection: str, node_type: NodeType, key: str, **props: Any) -> Node:
    return Node(
        collection=collection, type=node_type, key=key, labels=["TK"], props=props
    )


def test_the_memorandum_of_the_first_reading_explains_what_the_second_made_law(
    database: str,
) -> None:
    store = ArangoStore()
    with NodeWriter(store) as writer:
        writer.add_all(
            [
                _node(
                    COLLECTION_DOSSIERS,
                    NodeType.DOSSIER,
                    "35418",
                    number="35418",
                    label="35418",
                ),
                _node(
                    COLLECTION_DOSSIERS,
                    NodeType.DOSSIER,
                    "35785",
                    number="35785",
                    label="35785",
                ),
                _node(
                    COLLECTION_DOCUMENTS,
                    NodeType.DOCUMENT,
                    "mvt_first",
                    kind="Memorie van toelichting",
                ),
                _node(
                    COLLECTION_DOCUMENTS,
                    NodeType.DOCUMENT,
                    "mvt_second",
                    kind="Memorie van toelichting",
                ),
                _node(
                    COLLECTION_INSTRUMENTS,
                    NodeType.INSTRUMENT,
                    "stb_2022_332",
                    publication_kind="Stb",
                ),
                _node(
                    COLLECTION_ARTICLES,
                    NodeType.ARTICLE,
                    "bwbr0001840_13",
                    bwb_id="BWBR0001840",
                    article_number="13",
                ),
            ]
        )
    edges = EdgeWriter(store, what=None)
    edges.add(
        f"{COLLECTION_DOCUMENTS}/mvt_first", FIRST, RELATION_PART_OF, source="test"
    )
    edges.add(
        f"{COLLECTION_DOCUMENTS}/mvt_second", SECOND, RELATION_PART_OF, source="test"
    )
    edges.add(
        f"{COLLECTION_INSTRUMENTS}/stb_2022_332",
        SECOND,
        RELATION_LEGISLATED_IN,
        source="test",
    )
    edges.add(
        f"{COLLECTION_INSTRUMENTS}/stb_2022_332",
        ARTICLE,
        RELATION_AMENDS,
        source="test",
    )
    edges.flush()

    def targets() -> dict[str, list[str]]:
        rows = memorandum_targets(store, sections_source="mvt-section-linker")
        return {row["document"]: row["targets"] for row in rows}

    assert targets() == {f"{COLLECTION_DOCUMENTS}/mvt_second": [ARTICLE]}

    edges.add(SECOND, FIRST, RELATION_SECOND_READING_OF, source="test")
    edges.flush()
    assert targets() == {
        f"{COLLECTION_DOCUMENTS}/mvt_second": [ARTICLE],
        f"{COLLECTION_DOCUMENTS}/mvt_first": [ARTICLE],
    }
