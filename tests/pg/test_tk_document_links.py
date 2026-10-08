"""``retrieve tk-document-links`` and ``normalize tk-document-links`` on a real PostgreSQL:
the links of a document stored as a raw record of their own, and written as edges between
the nodes that exist."""

from __future__ import annotations

import datetime as dt
from typing import Any

from lawgraph.db import GraphStore
from lawgraph.pipelines.normalize.tk_document_links import (
    TKDocumentLinksNormalizePipeline,
)
from lawgraph.pipelines.retrieve.tk_document_links import (
    TKDocumentLinksRetrievePipeline,
)

STENOGRAM = "9cd4c32c-77fb-4713-821d-faf5ebd49b61"  # 2023D18976, 28 March 2023
DEBATE = "a76eec4d-9cde-48de-aefa-6385e69dd0e1"  # 2023A00493, its tweeminutendebat


class _Client:
    """The Gegevensmagazijn as ``fetch_document_links`` reads it."""

    on_total: Any = None

    def __init__(self) -> None:
        self.since: list[Any] = []

    def fetch_document_links(self, since: Any = None) -> Any:
        self.since.append(since)
        return iter(
            [
                {"Id": STENOGRAM, "Activiteit": [{"Id": DEBATE}]},
                {"Id": "letter", "BijlageDocument": [{"Id": "memo"}, {"Id": "report"}]},
                {"Id": "report", "BronDocument": [{"Id": "letter"}]},
                {"Id": "gone", "Verwijderd": True, "BronDocument": [{"Id": "letter"}]},
                {"Activiteit": [{"Id": DEBATE}]},  # no id: not stored
            ]
        )


def test_the_links_are_stored_and_written_as_edges(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "documents",
        [
            {"_key": key, "type": "document", "labels": ["TK"], "props": {}}
            for key in (
                "9cd4c32c_77fb_4713_821d_faf5ebd49b61",
                "letter",
                "memo",
                "report",
                "gone",
            )
        ],
    )
    store.bulk_insert_or_update_nodes(
        "activities",
        [
            {
                "_key": "a76eec4d_9cde_48de_aefa_6385e69dd0e1",
                "type": "activity",
                "labels": ["TK"],
                "props": {"number": "2023A00493"},
            }
        ],
    )
    client = _Client()
    since = dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc)
    retrieved = TKDocumentLinksRetrievePipeline(store, client).run(since=since)  # type: ignore[arg-type]
    assert client.since == [since]
    assert retrieved.created == 4 and retrieved.skipped == 1

    result = TKDocumentLinksNormalizePipeline(store=store).run()
    assert not result.errors
    edges = {
        (row["from_id"], row["relation"], row["to_id"])
        for row in store.query(
            "SELECT from_id, relation, to_id FROM edges WHERE source = 'tk-document-links'"
        )
    }
    # the stenogram hangs on its debate; the letter has its attachments, named from either
    # side; a deleted paper makes no edge
    assert edges == {
        (
            "documents/9cd4c32c_77fb_4713_821d_faf5ebd49b61",
            "MADE_IN",
            "activities/a76eec4d_9cde_48de_aefa_6385e69dd0e1",
        ),
        ("documents/memo", "ACCOMPANIES", "documents/letter"),
        ("documents/report", "ACCOMPANIES", "documents/letter"),
    }
