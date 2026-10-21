"""The edges normalize derives from a record go when the record no longer names their end: a
paper moved to another dossier, a commitment whose letter changed or that a letter fulfilled,
a case with another submitter or committee. Edges of the same relation and source to other
tables stay."""

from __future__ import annotations

from typing import Any

from lawgraph.core.models import Node
from lawgraph.db import GraphStore, make_edge_doc
from lawgraph.pipelines.normalize import _tk_cases as tk_cases
from lawgraph.pipelines.normalize.tk_case_actors import link_case_actors

SOURCE = "tk-dossiers"


def _nodes(store: GraphStore, collection: str, *keys: str, **props: Any) -> None:
    store.bulk_insert_or_update_nodes(
        collection,
        [
            {"key": k, "type": collection[:-1], "labels": [], "props": dict(props)}
            for k in keys
        ],
    )


def _edges(store: GraphStore, relation: str) -> list[tuple[str, str]]:
    return [
        (row["from_id"], row["to_id"])
        for row in store.query(
            "SELECT from_id, to_id FROM edges WHERE relation = %(r)s ORDER BY key",
            {"r": relation},
        )
    ]


def _decision(numbers: list[str]) -> Node:
    return Node(
        collection="decisions",
        key="b1",
        props={"dossier_numbers": numbers, "case_ids": []},
        _skip_validation=True,
    )


def test_a_decision_moved_to_another_dossier_loses_the_edge_to_the_first(
    store: GraphStore,
) -> None:
    _nodes(store, "dossiers", "36001", "36002")
    _nodes(store, "decisions", "b1")
    _nodes(store, "documents", "motie1")
    # ABOUT the motion, by the same source: another table, not of link_subjects
    store.bulk_insert_or_update_edges(
        [make_edge_doc("decisions/b1", "documents/motie1", "ABOUT", source=SOURCE)]
    )
    tk_cases.link_subjects(store, [_decision(["36001"])], "ABOUT", source=SOURCE)
    tk_cases.link_subjects(store, [_decision(["36002"])], "ABOUT", source=SOURCE)
    assert sorted(_edges(store, "ABOUT")) == [
        ("decisions/b1", "documents/motie1"),
        ("decisions/b1", "dossiers/36002"),
    ]


def test_a_commitment_whose_letter_changed_loses_the_first(store: GraphStore) -> None:
    _nodes(store, "documents", "brief1", "brief2")
    _nodes(store, "commitments", "t1")

    def commitment(letter: str) -> Node:
        return Node(
            collection="commitments",
            key="t1",
            props={"letter_ids": [letter]},
            _skip_validation=True,
        )

    tk_cases.link_letters_to_commitments(store, [commitment("brief1")], source=SOURCE)
    tk_cases.link_letters_to_commitments(store, [commitment("brief2")], source=SOURCE)
    assert _edges(store, "ANSWERS") == [("documents/brief2", "commitments/t1")]


def test_a_commitment_fulfilled_in_a_dossier_leaves_the_agenda(
    store: GraphStore,
) -> None:
    _nodes(store, "dossiers", "36001", "36002", "29389")
    _nodes(store, "activities", "a1")
    _nodes(store, "commitments", "t1", "t2")
    activities = {
        "a1": Node(
            collection="activities",
            key="a1",
            props={"number": "2025A04175", "dossier_numbers": ["36001", "36002"]},
            _skip_validation=True,
        )
    }

    def commitment(key: str, letter_dossiers: list[str]) -> Node:
        return Node(
            collection="commitments",
            key=key,
            props={"activity_number": "2025A04175", "letter_dossiers": letter_dossiers},
            _skip_validation=True,
        )

    tk_cases.link_commitments(
        store,
        {"t1": commitment("t1", []), "t2": commitment("t2", [])},
        activities,
        source=SOURCE,
    )
    # t1 fulfilled by a letter in 29389; t2 is not in this run and keeps its edges
    tk_cases.link_commitments(
        store, {"t1": commitment("t1", ["29389"])}, activities, source=SOURCE
    )
    assert [
        (row["from_id"], row["to_id"], row["basis"])
        for row in store.query(
            "SELECT from_id, to_id, doc -> 'meta' ->> 'basis' AS basis FROM edges"
            " WHERE relation = 'ABOUT' ORDER BY from_id, to_id"
        )
    ] == [
        ("commitments/t1", "dossiers/29389", "nakoming"),
        ("commitments/t2", "dossiers/36001", "agenda"),
        ("commitments/t2", "dossiers/36002", "agenda"),
    ]


def test_a_case_with_other_actors_loses_the_first(store: GraphStore) -> None:
    _nodes(store, "cases", "z1")
    _nodes(store, "members", "p1", "p2")
    _nodes(store, "committees", "c1", "c2")

    def actors(person: str, committee: str) -> list[tuple[str, dict[str, Any]]]:
        return [
            (
                "z1",
                {
                    "submitters": [{"person_id": person, "role": "Indiener"}],
                    "committee_ids": [committee],
                },
            )
        ]

    link_case_actors(store, actors("p1", "c1"), source="tk-case-actors")
    link_case_actors(store, actors("p2", "c2"), source="tk-case-actors")
    assert _edges(store, "AUTHORED") == [("members/p2", "cases/z1")]
    assert _edges(store, "LED_BY") == [("cases/z1", "committees/c2")]
