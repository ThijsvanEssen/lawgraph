"""The Eerste Kamer papers and the Tweede Kamer dossiers they belong to
(``db/queries/semantic/tk.py``), run for real: the unit tests replace the query with what it
answers here."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    SOURCE_EERSTEKAMER,
    SOURCE_TK,
)
from lawgraph.db import ArangoStore
from lawgraph.db.queries.semantic import tk as semantic_tk


def _node(key: str, kind: str, **props: Any) -> dict[str, Any]:
    return {"_key": key, "type": kind, "labels": [], "props": props}


def _dossiers(store: ArangoStore) -> None:
    store.bulk_insert_or_update_nodes(
        COLLECTION_DOSSIERS,
        [
            _node("37020", "dossier", number="37020"),
            _node("37020_xv", "dossier", number="37020", suffix="XV"),
        ],
    )


def _paper(key: str, number: str, suffix: str | None = None, **props: Any) -> dict:
    props = {"source": SOURCE_EERSTEKAMER, "dossier_number": number, **props}
    if suffix:
        props["dossier_suffix"] = suffix
    return _node(key, "document", **props)


def test_a_paper_belongs_to_the_dossier_with_its_number_and_addition(
    database: str,
) -> None:
    store = ArangoStore()
    _dossiers(store)
    store.bulk_insert_or_update_nodes(
        COLLECTION_DOCUMENTS,
        [
            _paper("ek_chapter", "37020", "XV"),
            _paper("ek_nota", "37020"),
            _paper("ek_unknown", "37021"),  # no such dossier in the graph
            _paper("tk_paper", "37020", source=SOURCE_TK),  # not an Eerste Kamer paper
        ],
    )
    rows = semantic_tk.ek_papers_in_tk_dossiers(store)
    assert sorted((row["document_key"], row["dossier_key"]) for row in rows) == [
        ("ek_chapter", "37020_xv"),
        ("ek_nota", "37020"),
    ]


def test_every_paper_is_linked_not_the_first_ten_thousand(database: str) -> None:
    store = ArangoStore()
    _dossiers(store)
    papers = [_paper(f"ek_{n}", "37020") for n in range(10_001)]
    for start in range(0, len(papers), 2_000):
        store.bulk_insert_or_update_nodes(
            COLLECTION_DOCUMENTS, papers[start : start + 2_000]
        )
    assert sum(1 for _ in semantic_tk.ek_papers_in_tk_dossiers(store)) == 10_001
