"""Who sent a Tweede Kamer paper (``core.documents.document_sender``): every route that
names a document gives it as ``sender``, read from the signatures it already loads."""

from __future__ import annotations

from typing import Any

from lawgraph.api.schemas.documents import DocumentListItemDTO, DocumentTextResponse
from lawgraph.api.schemas.dossiers import DossierDocumentDTO, timeline_entry
from lawgraph.api.schemas.nodes import BaseNodeDTO
from lawgraph.config.constants import (
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    RELATION_PART_OF,
)
from lawgraph.db import GraphStore, make_edge_doc
from lawgraph.db.queries.documents import get_document, list_documents
from lawgraph.db.queries.dossiers import get_dossier_documents, get_dossier_timeline

_DOSSIER = f"{COLLECTION_DOSSIERS}/36901"
_SENDER = {
    "name": "E. Heinen",
    "function": "minister van Financiën",
    "faction": None,
    "capacity": "bewindspersoon",
    "member_key": "p_9",
    "ministry": "fin",
}


def _seed(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        COLLECTION_DOSSIERS,
        [{"_key": "36901", "type": "dossier", "labels": ["TK"], "props": {}}],
    )
    actors: list[dict[str, Any]] = [
        {"name": "Griffier", "faction": "", "role": "Afzender", "capacity": "overig"},
        {
            "person_id": "p-9",
            "name": "E. Heinen",
            "faction": "",
            "role": "Eerste ondertekenaar",
            "function": "minister van Financiën",
            "capacity": "bewindspersoon",
        },
    ]
    store.bulk_insert_or_update_nodes(
        COLLECTION_DOCUMENTS,
        [
            {
                "_key": "d",
                "type": "document",
                "labels": ["TK"],
                "props": {
                    "source": "tk",
                    "kind": "Brief regering",
                    "title": "Voorjaarsnota",
                    "date": "2026-01-05",
                    "sequence": 3,
                    "dossier_number": "36901",
                    "actors": actors,
                },
            }
        ],
    )
    store.bulk_insert_or_update_edges(
        [make_edge_doc(f"{COLLECTION_DOCUMENTS}/d", _DOSSIER, RELATION_PART_OF)]
    )


def test_every_route_gives_the_sender_of_a_letter(store: GraphStore) -> None:
    _seed(store)

    (listed,) = list_documents(store, facets=False)["items"]
    (row,) = get_dossier_documents(store, _DOSSIER)["items"]
    (entry,) = get_dossier_timeline(store, _DOSSIER, order="asc", limit=10)
    doc = get_document(store, "d")
    assert doc is not None

    def dumped(sender: Any) -> dict[str, Any] | None:
        return sender.model_dump(mode="json") if sender else None

    assert dumped(DocumentListItemDTO.from_row(listed).sender) == _SENDER
    assert dumped(DossierDocumentDTO.from_row(row).sender) == _SENDER
    body = timeline_entry(entry).model_dump(mode="json")["body"]
    assert body["sender"] == _SENDER and "actors" not in body
    assert dumped(DocumentTextResponse.from_document(doc).sender) == _SENDER
    node = BaseNodeDTO.from_document(doc)
    assert node.props is not None and node.props["sender"] == _SENDER
