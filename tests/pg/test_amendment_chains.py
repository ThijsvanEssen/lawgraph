"""The amendments per period as the Kamer handles them (``amendment_chains`` of ``GET
/api/feed/periods``): each chain of papers that replace each other (REVISES) once, in the
month of its first paper, by the outcome of its last; and those of a dossier (``GET
/api/dossiers/{number}/amendments``) with their papers and the decision that decides them."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    COLLECTION_CASES,
    COLLECTION_DECISIONS,
    COLLECTION_DOSSIERS,
)
from lawgraph.core.models import NodeType
from lawgraph.db import EdgeWriter, GraphStore, NodeWriter
from lawgraph.db.queries.feed_events import get_periods, write_all
from lawgraph.db.queries.feed_sql import FeedFilters
from tests.asserts import assert_status, show_items
from tests.pg.feed_graph import (
    AALDERS,
    BAKKER,
    CO,
    FIRST,
    feed_actor,
    feed_document,
    feed_node,
)


def _document(key: str, date: str, sequence: int, case: str, subject: str) -> Any:
    return feed_document(key, "Amendement", date, "37000", sequence=sequence,
                     case_kinds=["Amendement"], case_ids=[case], subject=subject)  # fmt: skip


def _decision(key: str, case: str, date: str, **props: Any) -> Any:
    return feed_node(COLLECTION_DECISIONS, NodeType.DECISION, key, date=date,
                 primary_case_id=case, kind="Amendement", **props)  # fmt: skip


@pytest.fixture()
def chains(store: GraphStore) -> GraphStore:
    with NodeWriter(store) as writer:
        writer.add_all(
            [
                # 1. withdrawn: a decision without an outcome
                _document("a1", "2026-01-10", 1, "Z1", "Amendement over de grens"),
                _decision("d1", "Z1", "2026-01-20",
                          decision_kind="Stemmen - ingetrokken"),
                # 2. replaced: B2 replaces A2 and is voted on; the topic only in A2
                _document("a2", "2026-02-05", 2, "Z2", "Amendement over AI-toezicht"),
                _document("b2", "2026-03-01", 3, "Z3", "Gewijzigd amendement"),
                _decision("d2", "Z3", "2026-03-10", passed=True),
                # 3. held, then voted against
                _document("a3", "2026-04-02", 4, "Z4", "Amendement over de grens"),
                _decision("d3a", "Z4", "2026-04-10", decision_kind="Stemmen - aanhouden"),
                _decision("d3b", "Z4", "2026-04-20", passed=False),
                # 4. two papers merged into one; the oldest is C2; no decision yet
                _document("c1", "2026-05-03", 5, "Z5", "Amendement een"),
                _document("c2", "2026-05-01", 6, "Z6", "Amendement twee"),
                _document("c3", "2026-06-01", 7, "Z7", "Amendement samen"),
                *(feed_node(COLLECTION_CASES, NodeType.CASE, f"z{n}", external_id=f"Z{n}")
                  for n in range(1, 8)),
            ]
        )  # fmt: skip
    with EdgeWriter(store, what=None) as edges:
        for newer, older in (("b2", "a2"), ("c3", "c1"), ("c3", "c2")):
            edges.add(f"documents/{newer}", f"documents/{older}", "REVISES", source="t")
    write_all(store)
    return store


def _chains(store: GraphStore, filters: FeedFilters) -> list[tuple[str, dict]]:
    return [
        (p["period"], p["amendment_chains"])
        for p in get_periods(store, filters, "month")["periods"]
        if p["amendment_chains"]["count"]
    ]


def test_each_chain_once_in_the_month_of_its_first_paper_by_its_outcome(
    chains: GraphStore,
) -> None:
    def counts(**outcome: int) -> dict[str, int]:
        found = {"count": sum(outcome.values()), "aangenomen": 0, "verworpen": 0}
        return {**found, "other": 0, **outcome}

    assert _chains(chains, FeedFilters()) == [
        ("2026-01-01", counts(other=1)),  # withdrawn
        ("2026-02-01", counts(aangenomen=1)),  # replaced: the month of A2, B2's vote
        ("2026-04-01", counts(verworpen=1)),  # held, then voted against
        ("2026-05-01", counts(other=1)),  # merged: one, from C2; not voted yet
    ]


def test_a_chain_counts_for_a_topic_when_any_of_its_papers_holds_it(
    chains: GraphStore,
) -> None:
    # only A2 names AI; the chain counts, in A2's month, with B2's outcome
    found = _chains(chains, FeedFilters(q=("ai",)))
    assert [(period, c["count"], c["aangenomen"]) for period, c in found] == [
        ("2026-02-01", 1, 1)
    ]


def test_a_period_of_chains_alone_and_the_days_of_the_first_paper(
    chains: GraphStore,
) -> None:
    # March holds B2's paper but no chain begins in it
    march = get_periods(
        chains, FeedFilters(since="2026-03-01", until="2026-03-31"), "month"
    )["periods"]
    assert [
        (p["period"], p["counts"].get("Amendement"), p["amendment_chains"]["count"])
        for p in march
    ] == [("2026-03-01", 1, 0)]


def test_no_chains_when_the_kinds_leave_the_amendments_out(chains: GraphStore) -> None:
    periods = get_periods(chains, FeedFilters(kinds=("Motie",)), "month")["periods"]
    failing = [p for p in periods if "amendment_chains" in p]
    assert not failing, show_items(failing)


@pytest.fixture()
def dossier(chains: GraphStore) -> Iterator[TestClient]:
    """The chains as documents of dossier 37000, with a fifth amendment E1 whose case is not
    done; the decisions ABOUT the cases they single out, as the source links them."""
    with NodeWriter(chains) as writer:
        writer.add_all(
            [
                feed_node(COLLECTION_DOSSIERS, NodeType.DOSSIER, "37000", number="37000"),
                feed_document("e1", "Amendement", "2026-07-01", "37000", sequence=8,
                              case_kinds=["Amendement"], case_ids=["Z8"],
                              subject="Amendement acht",
                              actors=[feed_actor(BAKKER, "f-vvd", CO, "kamerlid"),
                                      feed_actor(AALDERS, "f-cda", FIRST, "kamerlid")]),
                # the case of E1, not done (Z1 to Z7 are the cases of the chains)
                feed_node(COLLECTION_CASES, NodeType.CASE, "z8", done=False),
            ]
        )  # fmt: skip
    with EdgeWriter(chains, what=None) as edges:
        for document in ("a1", "a2", "b2", "a3", "c1", "c2", "c3", "e1"):
            edges.add(f"documents/{document}", "dossiers/37000", "PART_OF", source="t")
        for decision, case in (("d1", 1), ("d2", 3), ("d3a", 4), ("d3b", 4)):
            edges.add(f"decisions/{decision}", f"cases/z{case}", "ABOUT", source="t")
    write_all(chains)
    app.dependency_overrides[get_store] = lambda: chains
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_store, None)


def test_the_amendments_of_a_dossier_each_chain_once_with_its_decision(
    dossier: TestClient,
) -> None:
    answer = dossier.get("/api/dossiers/37000/amendments")
    assert_status(answer, 200)
    chains = answer.json()["chains"]
    assert [
        (
            c["id"],
            [p["number"] for p in c["documents"]],
            c["outcome"],
            c["merged"],
            (c["decision"] or {}).get("key"),
            (c["decision"] or {}).get("outcome"),
            c["waiting"],
        )
        for c in chains
    ] == [
        ("documents/a1", ["1"], "other", False, "d1", "ingetrokken", False),
        ("documents/b2", ["2", "3"], "aangenomen", False, "d2", "aangenomen", False),
        # held, then voted: the vote decides
        ("documents/a3", ["4"], "verworpen", False, "d3b", "verworpen", False),
        # merged: C2 is the oldest; no decision, and nothing says its case is not done
        ("documents/c3", ["6", "5", "7"], "other", True, None, None, False),
        ("documents/e1", ["8"], "other", False, None, None, True),
    ]
    replaced = chains[1]["documents"]
    assert [(p["id"], p["replaces"], p["replaced_by"]) for p in replaced] == [
        ("documents/a2", [], ["documents/b2"]),
        ("documents/b2", ["documents/a2"], []),
    ]
    assert [(s["name"], s["role"]) for s in chains[4]["submitters"]] == [
        ("A. Aalders", "indiener"),
        ("B. Bakker", "medeindiener"),
    ]
    assert_status(dossier.get("/api/dossiers/37001/amendments"), 404)
