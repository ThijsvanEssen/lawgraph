"""The signals per dossier ``normalize tk-dossiers`` backfills titles and phases from
(``db/queries/normalize/tk.py``), run for real: the unit tests replace the query."""

from __future__ import annotations

from lawgraph.config.constants import (
    COLLECTION_ACTIVITIES,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    RELATION_ABOUT,
    RELATION_PART_OF,
)
from lawgraph.db import ArangoStore, make_edge_doc
from lawgraph.db.queries.normalize import tk as normalize_tk


def test_the_signals_of_a_dossier_are_the_few_fields_used_not_whole_documents(
    database: str,
) -> None:
    """A whole document (its text, its payload) per paper of 500 dossiers is held in the
    memory of the server; the backfill reads a few fields of each."""
    store = ArangoStore()
    store.bulk_insert_or_update_nodes(
        COLLECTION_DOSSIERS,
        [
            {
                "_key": "36000",
                "type": "dossier",
                "labels": [],
                "props": {"number": "36000"},
            }
        ],
    )
    store.bulk_insert_or_update_nodes(
        COLLECTION_DOCUMENTS,
        [
            {
                "_key": "d1",
                "type": "document",
                "labels": ["TK"],
                "props": {
                    "kind": "Voorstel van wet",
                    "date": "2026-01-02",
                    "title": "Wet X",
                    "dossier_numbers": ["36000"],
                    "case_kinds": ["Wetgeving"],
                    "dossier_number": "36000",
                    "sequence": 2,
                    "text": "x" * 10_000,
                    "raw": {"Id": "d1"},
                },
            }
        ],
    )
    store.bulk_insert_or_update_nodes(
        COLLECTION_ACTIVITIES,
        [
            {
                "_key": "a1",
                "type": "activity",
                "labels": [],
                "props": {"kind": "Plenair debat", "date": "2026-02-03", "status": "x"},
            }
        ],
    )
    store.bulk_insert_or_update_edges(
        [
            make_edge_doc("documents/d1", "dossiers/36000", RELATION_PART_OF),
            make_edge_doc("activities/a1", "dossiers/36000", RELATION_ABOUT),
        ]
    )

    (row,) = normalize_tk.dossier_signals(store, ["dossiers/36000"])
    assert row["dossier_id"] == "dossiers/36000"
    assert row["case_kinds"] == ["Wetgeving"]
    assert row["docs"] == [
        {
            "kind": "Voorstel van wet",
            "date": "2026-01-02",
            "title": "Wet X",
            "own": ["36000", None],
            "sequence": 2,
        }
    ]
    assert row["activities"] == [
        {"kind": "Plenair debat", "date": "2026-02-03", "status": "x"}
    ]
    assert row["decisions"] == []
