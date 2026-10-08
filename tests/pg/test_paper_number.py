"""The number of a paper in its dossier (``core.documents.paper_number``): the nr. of a
Tweede Kamer paper, the letter of an Eerste Kamer one. Every route that names a document
gives it as ``number``, read from the props it already loads."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.api.schemas.documents import DocumentListItemDTO, DocumentTextResponse
from lawgraph.api.schemas.dossiers import DossierDocumentDTO
from lawgraph.api.schemas.nodes import BaseNodeDTO
from lawgraph.config.constants import (
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    RELATION_PART_OF,
)
from lawgraph.db import GraphStore, make_edge_doc
from lawgraph.db.queries.documents import get_document, list_documents
from lawgraph.db.queries.dossiers import get_dossier_documents
from lawgraph.db.queries.search import search_all

_PAPERS: dict[str, tuple[list[str], dict[str, Any], str]] = {
    "tk": (["TK"], {"source": "tk", "sequence": 12}, "12"),
    "ek": (["EersteKamer", "EK"], {"source": "eerstekamer", "number": "A"}, "A"),
}


def _seed(store: GraphStore, labels: list[str], props: dict[str, Any]) -> None:
    store.bulk_insert_or_update_nodes(
        COLLECTION_DOSSIERS,
        [{"_key": "36901", "type": "dossier", "labels": ["TK"], "props": {}}],
    )
    store.bulk_insert_or_update_nodes(
        COLLECTION_DOCUMENTS,
        [
            {
                "_key": "d",
                "type": "document",
                "labels": labels,
                "props": {
                    "kind": "Verslag",
                    "title": "Verslag over de huurwet",
                    "date": "2026-01-05",
                    "dossier_number": "36901",
                    "dossier_numbers": ["36901"],
                    **props,
                },
            }
        ],
    )
    store.bulk_insert_or_update_edges(
        [
            make_edge_doc(
                f"{COLLECTION_DOCUMENTS}/d",
                f"{COLLECTION_DOSSIERS}/36901",
                RELATION_PART_OF,
            )
        ]
    )


@pytest.mark.parametrize("paper", list(_PAPERS))
def test_every_route_gives_the_number_of_a_paper(store: GraphStore, paper: str) -> None:
    labels, props, number = _PAPERS[paper]
    _seed(store, labels, props)

    (listed,) = list_documents(store, facets=False)["items"]
    (hit,) = search_all(store, q="huurwet", types=["documents"])["documents"]
    (row,) = get_dossier_documents(store, f"{COLLECTION_DOSSIERS}/36901")["items"]
    doc = get_document(store, "d")
    assert doc is not None

    assert DocumentListItemDTO.from_row(listed, {}).number == number
    assert hit["extra"]["number"] == number
    assert DossierDocumentDTO.from_row(row).number == number
    assert DocumentTextResponse.from_document(doc).number == number
    node = BaseNodeDTO.from_document(doc)
    assert node.props is not None and node.props["number"] == number
