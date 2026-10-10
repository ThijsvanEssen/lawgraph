"""The chain of an amended amendment: the papers a paper replaces and those that replace it
(``REVISES`` with the rule ``vervanging``, from ``Zaak.VervangenVanuit``), on the papers of
a dossier and on the paper itself, so the timetable of amendments reads them from the list
of papers."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    RELATION_PART_OF,
    RELATION_REVISES,
)
from lawgraph.db import GraphStore, make_edge_doc

D = COLLECTION_DOCUMENTS


def _paper(sequence: int) -> dict[str, Any]:
    return {
        "_key": f"kst_36901_{sequence}",
        "type": "document",
        "labels": ["TK"],
        "props": {
            "source": "tk",
            "kind": "Amendement",
            "title": f"Amendement nr. {sequence}",
            "date": f"2026-01-{sequence % 28 + 1:02d}",
            "dossier_number": "36901",
            "dossier_numbers": ["36901"],
            "sequence": sequence,
            "case_kinds": ["Amendement"],
        },
    }


def _seed(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        COLLECTION_DOSSIERS,
        [{"_key": "36901", "type": "dossier", "labels": ["TK"], "props": {}}],
    )
    numbers = (12, 27, 30, 40, 41, 42, 50)
    store.bulk_insert_or_update_nodes(D, [_paper(n) for n in numbers])

    def revises(new: int, old: int, rule: str = "vervanging") -> dict[str, Any]:
        return make_edge_doc(
            f"{D}/kst_36901_{new}",
            f"{D}/kst_36901_{old}",
            RELATION_REVISES,
            source="tk-dossier-relations",
            meta={"rule": rule},
        )

    store.bulk_insert_or_update_edges(
        [
            make_edge_doc(
                f"{D}/kst_36901_{n}", f"{COLLECTION_DOSSIERS}/36901", RELATION_PART_OF
            )
            for n in numbers
        ]
        # 12 ← 27 ← 30, and two merged into one: 40 and 41 ← 42
        + [revises(27, 12), revises(30, 27), revises(42, 40), revises(42, 41)]
        # a revision of another rule is no replacement
        + [revises(50, 12, rule="begrotingswijziging")]
    )


def _sequences(refs: list[dict[str, Any]]) -> list[int]:
    return [ref["sequence"] for ref in refs]


def test_the_papers_of_a_dossier_carry_their_chain(store: GraphStore) -> None:
    _seed(store)
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        items = client.get("/api/dossiers/36901/documents").json()["items"]
        chain = {
            item["sequence"]: (
                _sequences(item["replaces"]),
                _sequences(item["replaced_by"]),
            )
            for item in items
        }
        assert chain == {
            12: ([], [27]),
            27: ([12], [30]),
            30: ([27], []),
            40: ([], [42]),
            41: ([], [42]),
            42: ([40, 41], []),
            50: ([], []),
        }
        # the paper itself, by its key
        paper = client.get("/api/documents/kst_36901_27").json()
        assert paper["replaces"] == [
            {"id": f"{D}/kst_36901_12", "key": "kst_36901_12", "sequence": 12}
        ]
        assert _sequences(paper["replaced_by"]) == [30]
        assert client.get("/api/documents/kst_36901_50").json()["replaces"] == []
    finally:
        app.dependency_overrides.pop(get_store, None)
