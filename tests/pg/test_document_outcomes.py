"""How a motion and an amendment ended (``semantic tk-paper-outcomes``), on the papers of a
dossier, on the list of papers, on the paper itself and on the canvas; and the Kamerstuk a vote
was taken on (``primary_document`` of ``/api/decisions/{key}``).

As the Cyberbeveiligingswet: amendement nr. 25 aangenomen 150-0, nr. 12 verworpen 65-85,
motie nr. 19 held twice and replaced by nr. 31, aangenomen 139-11; a motion of the Eerste
Kamer without a decision, verworpen as its page states.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.db import GraphStore, make_edge_doc
from lawgraph.pipelines.semantic.tk_paper_outcomes import (
    TKPaperOutcomesSemanticPipeline,
)

DOSSIER = "36800"


def _document(
    sequence: int | str, kind: str, date: str, **props: Any
) -> dict[str, Any]:
    ek = isinstance(sequence, str)
    return {
        "key": f"kst_{DOSSIER}_{str(sequence).lower()}",
        "type": "document",
        "labels": ["EersteKamer", "EK"] if ek else ["TK"],
        "props": {
            "source": "eerstekamer" if ek else "tk",
            "kind": kind,
            "title": f"{kind} nr. {sequence}",
            "date": date,
            "dossier_number": DOSSIER,
            "dossier_numbers": [DOSSIER],
            **({"number": sequence} if ek else {"sequence": sequence}),
            **props,
        },
    }


def _decision(
    key: str, case: str, kind: str, date: str, **props: Any
) -> dict[str, Any]:
    return {
        "key": key,
        "type": "decision",
        "labels": ["TK"],
        "props": {
            "chamber": "TK",
            "date": date,
            "primary_case_id": case,
            "primary_case_kind": kind,
            "case_ids": [case],
            "dossier_numbers": [DOSSIER],
            **props,
        },
    }


def _seed(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "dossiers", [{"key": DOSSIER, "type": "dossier", "labels": ["TK"],
                      "props": {"label": DOSSIER}}],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "documents",
        [
            _document(12, "Amendement", "2026-03-20"),
            _document(25, "Amendement", "2026-04-07"),
            _document(19, "Motie", "2026-03-24"),
            _document(31, "Motie (gewijzigd/nader)", "2026-04-14"),
            _document("C", "Motie", "2026-10-06", status="verworpen"),
            # a letter of the case of nr. 25, after it: the vote is not on it
            _document(30, "Brief regering", "2026-04-10"),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "cases",
        [
            {"key": key.lower().replace("-", "_"), "type": "case", "labels": [],
             "props": {"external_id": key}}
            for key in ("Z-12", "Z-25", "Z-19", "Z-31")
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "decisions",
        [
            _decision("d_12", "Z-12", "Amendement", "2026-04-15", passed=False,
                      decision_kind="Stemmen - verworpen",
                      tally={"Voor": 65, "Tegen": 85}),
            _decision("d_25", "Z-25", "Amendement", "2026-04-15", passed=True,
                      decision_kind="Stemmen - aangenomen", tally={"Voor": 150}),
            _decision("d_19a", "Z-19", "Motie", "2026-03-31",
                      decision_kind="Stemmen - aangehouden"),
            _decision("d_19b", "Z-19", "Motie", "2026-04-07",
                      decision_kind="Stemmen - aangehouden"),
            _decision("d_31", "Z-31", "Motie", "2026-04-15", passed=True,
                      decision_kind="Stemmen - aangenomen",
                      tally={"Voor": 139, "Tegen": 11}),
        ],
    )  # fmt: skip
    papers = ("12", "25", "19", "31", "c", "30")
    cases = {"12": "z_12", "25": "z_25", "19": "z_19", "31": "z_31", "30": "z_25"}
    store.bulk_insert_or_update_edges(
        [
            make_edge_doc(
                f"documents/kst_{DOSSIER}_{n}", f"dossiers/{DOSSIER}", "PART_OF"
            )
            for n in papers
        ]
        + [
            make_edge_doc(f"documents/kst_{DOSSIER}_{n}", f"cases/{case}", "PART_OF")
            for n, case in cases.items()
        ]
        + [
            make_edge_doc(f"decisions/d_{n}", f"cases/z_{n.rstrip('ab')}", "ABOUT")
            for n in ("12", "25", "19a", "19b", "31")
        ]
        + [
            make_edge_doc(
                f"documents/kst_{DOSSIER}_31",
                f"documents/kst_{DOSSIER}_19",
                "REVISES",
                source="tk-dossier-relations",
                meta={"rule": "vervanging"},
            )
        ]
    )


@pytest.fixture()
def client(store: GraphStore) -> Iterator[TestClient]:
    _seed(store)
    app.dependency_overrides[get_store] = lambda: store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_store, None)


def _outcomes(items: list[dict[str, Any]]) -> dict[str, tuple[Any, ...]]:
    return {
        item["number"]: (item["outcome"], item["decided_on"], item["tally"],
                         item["decision"])
        for item in items
    }  # fmt: skip


EXPECTED = {
    "12": ("verworpen", "2026-04-15", {"Voor": 65, "Tegen": 85}, "d_12"),
    "25": ("aangenomen", "2026-04-15", {"Voor": 150}, "d_25"),
    # held twice, then replaced: held, the latest
    "19": ("aangehouden", "2026-04-07", None, "d_19b"),
    "31": ("aangenomen", "2026-04-15", {"Voor": 139, "Tegen": 11}, "d_31"),
    # the Eerste Kamer: as its page states it
    "C": ("verworpen", None, None, None),
    "30": (None, None, None, None),
}


def test_every_motion_and_amendment_says_how_it_ended(
    client: TestClient, store: GraphStore
) -> None:
    result = TKPaperOutcomesSemanticPipeline(store).run()
    assert result.updated == 5

    items = client.get(f"/api/dossiers/{DOSSIER}/documents").json()["items"]
    assert _outcomes(items) == EXPECTED
    listed = client.get("/api/documents", params={"dossier": DOSSIER}).json()["items"]
    assert _outcomes(listed) == EXPECTED
    paper = client.get(f"/api/documents/kst_{DOSSIER}_25").json()
    assert (paper["outcome"], paper["tally"], paper["decision"]) == (
        "aangenomen",
        {"Voor": 150},
        "d_25",
    )


def test_the_canvas_carries_the_outcome_alone(
    client: TestClient, store: GraphStore
) -> None:
    TKPaperOutcomesSemanticPipeline(store).run()
    answer = client.get(
        f"/api/nodes/dossiers/{DOSSIER}", params={"props": "canvas", "limit": 50}
    ).json()
    props = {
        item["key"]: item["props"]
        for bucket in answer["neighbors"]["buckets"]
        for item in bucket["items"]
        if item["collection"] == "documents"
    }
    assert props[f"kst_{DOSSIER}_12"]["outcome"] == "verworpen"
    assert "tally" not in props[f"kst_{DOSSIER}_12"]


def test_a_run_again_writes_only_what_changed(
    client: TestClient, store: GraphStore
) -> None:
    TKPaperOutcomesSemanticPipeline(store).run()
    assert TKPaperOutcomesSemanticPipeline(store).run().updated == 0
    # the vote on nr. 12 turns out withdrawn instead: its outcome changes, and nr. 25 loses
    # its decision: all null
    store.bulk_insert_or_update_nodes(
        "decisions",
        [_decision("d_12", "Z-12", "Amendement", "2026-04-15", passed=None,
                   decision_kind="Stemmen - ingetrokken", tally=None)],
    )  # fmt: skip
    store.execute("DELETE FROM decisions WHERE key = 'd_25'")
    assert TKPaperOutcomesSemanticPipeline(store).run().updated == 2
    items = client.get(f"/api/dossiers/{DOSSIER}/documents").json()["items"]
    found = _outcomes(items)
    assert found["12"] == ("ingetrokken", "2026-04-15", None, "d_12")
    assert found["25"] == (None, None, None, None)


def test_a_vote_names_the_kamerstuk_it_was_taken_on(client: TestClient) -> None:
    paper = client.get("/api/decisions/d_31").json()["primary_document"]
    assert paper == {
        "id": f"documents/kst_{DOSSIER}_31",
        "key": f"kst_{DOSSIER}_31",
        "kind": "Motie (gewijzigd/nader)",
        "title": "Motie (gewijzigd/nader) nr. 31",
        "number": "31",
        "dossier_number": DOSSIER,
        "date": "2026-04-14",
        "path": f"/kamerstukken/{DOSSIER}/31",
    }
