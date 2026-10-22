"""Motions of censure and of no confidence (``semantic tk-motion-kinds``): the kind on the
motion and on the vote on it, the filter and facet of ``/api/decisions`` and the filter of
``/api/documents``.

As Kamerstuk 37020-XVI, nr. 60 (SGP, 15 October 2026, afkeuring, not voted yet), a motion
of no confidence voted down, and a near miss: a motion that asks to convey "afkeuring" abroad.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.db import GraphStore, make_edge_doc
from lawgraph.pipelines.semantic.tk_motion_kinds import TKMotionKindsSemanticPipeline
from tests.asserts import assert_status

DOSSIER = "37020-XVI"

CENSURE = (
    "Motie van het lid Diederik van Dijk over afkeuring uitspreken over het beleid van de "
    "regering inzake de pilot die abortussen vanaf 22 weken zwangerschap bij gezonde "
    "kindjes toegankelijker maakt "
)
NO_CONFIDENCE = (
    "Motie van het lid Wilders over het opzeggen van het vertrouwen in het kabinet"
)
NEAR_MISS = (
    "Motie van de leden Piri en Paternotte over afkeuring over de arrestatie van "
    "Imamoglu actief uitdragen "
)


def _motion(sequence: int, subject: str, date: str) -> dict[str, Any]:
    return {
        "key": f"kst_37020_xvi_{sequence}",
        "type": "document",
        "labels": ["TK"],
        "props": {
            "source": "tk",
            "kind": "Motie",
            "title": subject.strip(),
            "subject": subject,
            "date": date,
            "dossier_number": "37020",
            "dossier_suffix": "XVI",
            "dossier_numbers": [DOSSIER],
            "sequence": sequence,
        },
    }


def _decision(key: str, case: str, subject: str, date: str) -> dict[str, Any]:
    return {
        "key": key,
        "type": "decision",
        "labels": ["TK"],
        "props": {
            "chamber": "TK",
            "date": date,
            "subject": subject,
            "kind": "Motie",
            "primary_case_id": case,
            "primary_case_kind": "Motie",
            "case_ids": [case],
            "dossier_numbers": [DOSSIER],
            "decision_kind": "Stemmen - verworpen",
            "passed": False,
            "vote_kind": "faction",
            "tally": {"Voor": 20, "Tegen": 130},
        },
    }


def _seed(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "documents",
        [
            _motion(60, CENSURE, "2026-10-15"),
            _motion(61, NO_CONFIDENCE, "2026-09-17"),
            _motion(62, NEAR_MISS, "2026-09-17"),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "cases",
        [
            {"key": f"z_{n}", "type": "case", "labels": [], "props": {}}
            for n in (61, 62)
        ],
    )
    store.bulk_insert_or_update_nodes(
        "decisions",
        [
            _decision("d_61", "z_61", NO_CONFIDENCE, "2026-09-22"),
            _decision("d_62", "z_62", NEAR_MISS, "2026-09-22"),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "factions",
        [
            {
                "key": "sgp",
                "type": "faction",
                "labels": [],
                "props": {"abbreviation": "SGP"},
            }
        ],
    )
    store.bulk_insert_or_update_edges(
        [
            make_edge_doc(f"documents/kst_37020_xvi_{n}", f"cases/z_{n}", "PART_OF")
            for n in (61, 62)
        ]
        + [make_edge_doc(f"decisions/d_{n}", f"cases/z_{n}", "ABOUT") for n in (61, 62)]
        + [
            make_edge_doc(
                "factions/sgp", "decisions/d_61", "VOTED",
                meta={"choice": "Tegen", "seats": 3},
            )
        ]
    )  # fmt: skip


@pytest.fixture()
def client(store: GraphStore) -> Iterator[TestClient]:
    _seed(store)
    app.dependency_overrides[get_store] = lambda: store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_store, None)


def test_the_motion_and_the_vote_on_it_carry_its_kind(
    client: TestClient, store: GraphStore
) -> None:
    assert TKMotionKindsSemanticPipeline(store).run().updated == 3

    kinds = {
        item["number"]: item["motion_kind"]
        for item in client.get("/api/documents", params={"dossier": DOSSIER}).json()[
            "items"
        ]
    }
    assert kinds == {"60": "censure", "61": "no_confidence", "62": None}
    paper = client.get("/api/documents/kst_37020_xvi_60").json()
    assert (paper["motion_kind"], paper["outcome"]) == ("censure", None)
    vote = client.get("/api/decisions/d_61").json()
    assert vote["motion_kind"] == "no_confidence"
    assert [(v["name"], v["choice"]) for v in vote["votes"]] == [("SGP", "Tegen")]
    assert client.get("/api/decisions/d_62").json()["motion_kind"] is None


def test_the_motions_of_a_kind_are_listed_alone(
    client: TestClient, store: GraphStore
) -> None:
    TKMotionKindsSemanticPipeline(store).run()

    def numbers(kinds: str) -> list[str]:
        answer = client.get("/api/documents", params={"motion_kind": kinds}).json()
        return [item["number"] for item in answer["items"]]

    assert numbers("censure,no_confidence") == ["60", "61"]
    assert numbers("censure") == ["60"]
    assert_status(
        client.get("/api/documents", params={"motion_kind": "afkeuring"}), 422
    )


def test_the_votes_are_filtered_and_counted_by_kind(
    client: TestClient, store: GraphStore
) -> None:
    TKMotionKindsSemanticPipeline(store).run()

    every = client.get("/api/decisions").json()
    assert every["facets"]["motion_kind"] == [
        {"value": "no_confidence", "count": 1, "passed": 0, "rejected": 1}
    ]
    kept = client.get(
        "/api/decisions", params={"motion_kind": "censure,no_confidence"}
    ).json()
    assert [item["key"] for item in kept["items"]] == ["d_61"]
    assert kept["items"][0]["motion_kind"] == "no_confidence"
    # its own facet counts without its own filter
    censure = client.get("/api/decisions", params={"motion_kind": "censure"}).json()
    assert censure["total"] == 0
    assert censure["facets"]["motion_kind"] == every["facets"]["motion_kind"]


def test_a_run_since_reads_the_new_and_a_full_run_clears_what_no_longer_holds(
    client: TestClient, store: GraphStore
) -> None:
    import datetime as dt

    since = dt.datetime(2026, 10, 1, tzinfo=dt.UTC)
    assert TKMotionKindsSemanticPipeline(store).run(since=since).updated == 1
    assert TKMotionKindsSemanticPipeline(store).run().updated == 2
    # the subject changed at the source: the kind goes
    store.bulk_insert_or_update_nodes(
        "documents",
        [_motion(61, "Motie van het lid Wilders over het kabinet", "2026-09-17")],
    )
    assert TKMotionKindsSemanticPipeline(store).run().updated == 1
    paper = client.get("/api/documents/kst_37020_xvi_61").json()
    assert paper["motion_kind"] is None


def test_the_name_of_a_kind_finds_its_motions_and_the_votes_on_them(
    client: TestClient, store: GraphStore
) -> None:
    """ "wantrouwen" and "motie van wantrouwen" find the motion of no confidence and the vote
    on it, whose subject says "het opzeggen van het vertrouwen", in full and while typing;
    "afkeuring" the motion of censure before the near miss that only holds the word; and
    ``motion_kind`` keeps a search to those motions."""
    TKMotionKindsSemanticPipeline(store).run()

    def found(q: str, mode: str, **params: str) -> dict[str, list[str]]:
        answer = client.get(
            "/api/search",
            params={
                "q": q,
                "types": ["documents", "decisions"],
                "mode": mode,
                **params,
            },
        )
        assert_status(answer, 200)
        results = answer.json()["results"]
        return {t: [h["key"] for h in hits] for t, hits in results.items()}

    for mode in ("full", "live"):
        for q in ("wantrouwen", "motie van wantrouwen"):
            assert found(q, mode) == {
                "documents": ["kst_37020_xvi_61"],
                "decisions": ["d_61"],
            }, (q, mode)
        assert found("afkeuring", mode)["documents"][0] == "kst_37020_xvi_60", mode
        assert found("motie", mode, motion_kind="no_confidence") == {
            "documents": ["kst_37020_xvi_61"],
            "decisions": ["d_61"],
        }, mode
    assert_status(
        client.get("/api/search", params={"q": "motie", "motion_kind": "afkeuring"}),
        422,
    )
