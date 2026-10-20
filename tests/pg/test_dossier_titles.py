"""``semantic tk-dossier-titles``: a dossier without a title or an opening date of its own (a
stub another source made: the Eerste Kamer, a reference) takes them from its papers, as
``normalize tk-dossiers`` gives its own dossiers, so the API reads them stored."""

from __future__ import annotations

import copy
from typing import Any

from lawgraph.db import GraphStore
from lawgraph.db.queries.dossiers import enrich_dossier_docs
from lawgraph.pipelines.semantic.tk_dossier_titles import (
    TKDossierTitlesSemanticPipeline,
)


def _paper(key: str, dossier: str, kind: str, title: str, date: str, n: int) -> Any:
    return {
        "key": key,
        "type": "document",
        "labels": ["TK"],
        "props": {
            "title": title,
            "kind": kind,
            "date": date,
            "dossier_numbers": [dossier],
            "dossier_number": dossier,
            "sequence": n,
            "text": "De hele tekst.",
        },
    }


def _graph(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "dossiers",
        [
            # a stub of the Eerste Kamer: a number, no title
            {"key": "36100", "type": "dossier", "labels": [], "props": {"number": "36100"}},
            # a title of its own without its source
            {
                "key": "36200",
                "type": "dossier",
                "labels": [],
                "props": {"number": "36200", "title": "Eigen titel", "opened_on": "2024-01-01"},
            },
            # nothing to take a title from
            {"key": "36300", "type": "dossier", "labels": [], "props": {"number": "36300"}},
        ],
    )  # fmt: skip
    papers = [
        _paper(
            "p1", "36100", "Memorie van toelichting", "MvT bij Wet X", "2025-03-02", 3
        ),
        _paper("p2", "36100", "Voorstel van wet", "Wet X", "2025-03-02", 2),
        _paper("p3", "36100", "Koninklijke boodschap", "Boodschap", "2025-03-01", 1),
        _paper("p4", "36200", "Brief regering", "Brief", "2024-02-01", 1),
    ]
    store.bulk_insert_or_update_nodes("documents", papers)
    store.bulk_insert_or_update_edges(
        [
            {
                "key": f"part-{p['key']}",
                "from_id": f"documents/{p['key']}",
                "to_id": f"dossiers/{p['props']['dossier_number']}",
                "relation": "PART_OF",
                "source": "test",
                "meta": {},
            }
            for p in papers
        ]
    )


def _props(store: GraphStore, key: str) -> dict[str, Any]:
    return dict(store.get_document("dossiers", key)["props"])  # type: ignore[index]


def test_a_dossier_without_a_title_takes_it_from_its_papers(store: GraphStore) -> None:
    _graph(store)
    result = TKDossierTitlesSemanticPipeline(store).run()
    assert result.updated == 2
    stub = _props(store, "36100")
    assert stub["title"] == "Wet X"
    assert stub["title_source"] == "document"
    assert stub["display_name"] == "Kamerstukdossier 36100: Wet X"
    assert stub["opened_on"] == "2025-03-01"
    own = _props(store, "36200")
    assert own["title"] == "Eigen titel"
    assert own["title_source"] == "dossier"
    assert own["opened_on"] == "2024-01-01"
    assert "title" not in _props(store, "36300")
    # a second run has nothing left to write
    assert TKDossierTitlesSemanticPipeline(store).run().updated == 0


def test_the_api_reads_what_the_step_wrote(store: GraphStore) -> None:
    """After the step, what the API derives of a dossier is what is stored."""
    _graph(store)
    TKDossierTitlesSemanticPipeline(store).run()
    stored = [store.get_document("dossiers", k) for k in ("36100", "36200", "36300")]
    expected = copy.deepcopy([d["props"] for d in stored])  # type: ignore[index]
    enriched = enrich_dossier_docs(store, copy.deepcopy(stored))  # type: ignore[arg-type]
    assert [d["props"] for d in enriched] == expected
