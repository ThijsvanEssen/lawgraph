"""The papers ``retrieve tk-content`` asks the repository for (``db/queries/gaps.py``), run
for real: the unit tests replace the query with what it answers here."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import COLLECTION_DOCUMENTS
from lawgraph.db import ArangoStore
from lawgraph.db.queries import gaps as gap_queries


def _paper(key: str, labels: list[str], **props: Any) -> dict[str, Any]:
    return {"_key": key, "type": "document", "labels": labels, "props": props}


def test_the_papers_of_a_kind_are_the_numbered_tk_papers_with_their_dossier(
    database: str,
) -> None:
    store = ArangoStore()
    numbered = {"dossier_number": "37020", "date": "2026-09-15"}
    store.bulk_insert_or_update_nodes(
        COLLECTION_DOCUMENTS,
        [
            _paper(
                "mvt",
                ["TK"],
                kind="Memorie van toelichting",
                title="Memorie",
                dossier_suffix="XV",
                sequence=3,
                **numbered,
            ),
            # without a kind: left out, not an error
            _paper("nokind", ["TK"], sequence=4, **numbered),
            # another kind, no number in the dossier, an Eerste Kamer paper
            _paper("motie", ["TK"], kind="Motie", sequence=5, **numbered),
            _paper("unnumbered", ["TK"], kind="Memorie van toelichting", **numbered),
            _paper(
                "ek", ["EK"], kind="Memorie van toelichting", sequence=6, **numbered
            ),
        ],
    )
    papers = list(gap_queries.papers_with_dossier(store, ["toelichting"]))
    assert papers == [
        {
            "key": "mvt",
            "title": "Memorie",
            "number": "37020",
            "suffix": "XV",
            "sequence": 3,
            "date": "2026-09-15",
        }
    ]
