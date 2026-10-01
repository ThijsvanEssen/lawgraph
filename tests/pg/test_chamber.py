"""The chamber of a document has one definition (``core.documents.CHAMBERS``): the list of
``/api/documents``, the hits of the search and ``chamber_of`` agree, also on a document
that would carry the labels of both chambers."""

from __future__ import annotations

import pytest

from lawgraph.config.constants import COLLECTION_DOCUMENTS
from lawgraph.core.documents import chamber_of
from lawgraph.db import GraphStore
from lawgraph.db.queries.documents import list_documents
from lawgraph.db.queries.search import search_all


@pytest.mark.parametrize("labels", [["TK"], ["EK"], ["EK", "TK"], ["TK", "EK"]])
def test_every_reading_of_the_chamber_agrees(
    store: GraphStore, labels: list[str]
) -> None:
    store.bulk_insert_or_update_nodes(
        COLLECTION_DOCUMENTS,
        [
            {
                "_key": "d",
                "type": "document",
                "labels": labels,
                "props": {"title": "Wijziging van de Huurwet", "date": "2025-01-01"},
            }
        ],
    )
    (listed,) = list_documents(store, facets=False)["items"]
    (hit,) = search_all(store, q="huurwet", types=["documents"])["documents"]
    assert listed["chamber"] == hit["extra"]["chamber"] == chamber_of(labels)
