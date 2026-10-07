"""The decision queries on a real PostgreSQL: the list with its filters and facets, a
decision with its votes, and the document a decision was about."""

from __future__ import annotations

import json
from typing import Any

import psycopg
import pytest

from lawgraph.db import GraphStore
from lawgraph.db.queries.decisions import (
    DecisionFilters,
    get_decision_detail,
    get_decision_document,
    get_decisions,
    get_document_decisions,
)


def _node(key: str, labels: list[str] | None = None, **props: Any) -> dict[str, Any]:
    return {"_key": key, "type": "decision", "labels": labels or [], "props": props}


def _vote(key: str, voter: str, decision: str, **meta: Any) -> dict[str, Any]:
    return {
        "_key": key,
        "_from": voter,
        "_to": f"decisions/{decision}",
        "relation": "VOTED",
        "source": "test",
        "meta": meta,
    }


def _part_of(key: str, document: str, case: str) -> dict[str, Any]:
    return {
        "_key": key,
        "_from": f"documents/{document}",
        "_to": f"cases/{case}",
        "relation": "PART_OF",
        "source": "test",
    }


def _keys(page: dict[str, Any]) -> list[str]:
    return [row["key"] for row in page["items"]]


def test_the_decisions_of_a_dossier_are_read_from_an_index(
    store: GraphStore, conn: psycopg.Connection
) -> None:
    """From ``tests/integration/test_api_documents.py``."""
    store.bulk_insert_or_update_nodes(
        "decisions",
        [
            _node(
                "stemming_1",
                ["TK"],
                date="2025-03-08",
                subject="Motie over wegen",
                decision_id="b1",
                passed=True,
                vote_kind="faction",
                tally={"Voor": 80, "Tegen": 70},
                voters={"Voor": 5, "Tegen": 4},
                dossier_numbers=["36000"],
            ),
            _node(
                "stemming_2",
                ["TK"],
                date="2025-03-09",
                passed=False,
                dossier_numbers=["36001", "36000"],
            ),
            _node(
                "stemming_3",
                ["TK"],
                date="2025-03-10",
                passed=True,
                dossier_numbers=["36001"],
            ),
        ],
    )
    page = get_decisions(store, DecisionFilters(dossier="36000"), limit=10)
    assert page["total"] == 2
    assert _keys(page) == ["stemming_2", "stemming_1"]
    assert get_decisions(store, DecisionFilters(dossier="36001"), limit=1)["total"] == 2
    nothing = get_decisions(store, DecisionFilters(dossier="99999"))
    assert (nothing["total"], nothing["items"]) == (0, [])
    assert nothing["facets"] == {"kind": [], "passed": [], "days": []}
    together = get_decisions(store, DecisionFilters(dossier="36000", passed=True))
    assert together["total"] == 1

    conn.execute("SET enable_seqscan = off")
    plan = "\n".join(
        row[0]
        for row in conn.execute(
            "EXPLAIN SELECT key FROM decisions d"
            " WHERE d.dossier_numbers @> ARRAY['36000']::text[]"
        )
    )
    assert "decisions_dossier_numbers" in plan, plan


@pytest.fixture()
def votes(store: GraphStore) -> GraphStore:
    store.bulk_insert_or_update_nodes(
        "decisions",
        [
            _node(
                "s1",
                ["TK"],
                date="2024-01-01",
                subject="Motie over de ÉCOLE",
                display_name="Motie 2024Z00001: Motie over de ÉCOLE",
                kind="Motie",
                primary_case_kind="Motie",
                passed=True,
                chamber="TK",
                decision_id="b1",
                dossier_numbers=["36000"],
                tally={"Voor": 80, "Tegen": 70},
                voters={"Voor": 3, "Tegen": 2},
            ),
            # the same day: the key settles it; no chamber stored: the label says it
            _node(
                "s0",
                ["EK", "TK"],
                date="2024-01-01",
                subject="Amendement",
                kind="Amendement",
                passed=False,
                chamber="",
                tally=None,
            ),
            _node("s2", ["EK"], date="2023-05-05", kind="Motie", passed=True),
            _node("s3", [], kind=None, passed=None),
            _node(
                "s4",
                ["TK"],
                date="2023-05-05",
                kind="Motie",
                passed=False,
                subject="motie",
            ),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "factions",
        [
            {
                "_key": "vvd",
                "type": "faction",
                "labels": [],
                "props": {"name": "Volkspartij", "abbreviation": "VVD"},
            },
            {
                "_key": "x",
                "type": "faction",
                "labels": [],
                "props": {"name": "B-partij", "abbreviation": None},
            },
            {
                "_key": "a",
                "type": "faction",
                "labels": [],
                "props": {"name": "B-partij"},
            },
        ],
    )
    store.bulk_insert_or_update_nodes(
        "members",
        [{"_key": "m1", "type": "member", "labels": [], "props": {"name": "Anna"}}],
    )
    store.bulk_insert_or_update_edges(
        [
            _vote("v1", "factions/vvd", "s1", choice="Voor", seats=30),
            _vote("v2", "factions/x", "s1", choice="Tegen", seats=40),
            _vote("v3", "factions/a", "s1", choice="Tegen", seats=40),
            _vote("v4", "members/m1", "s1", choice="Voor", seats=None),
            _vote("v5", "members/gone", "s1", choice="Voor", seats=1),
            _vote("v6", "factions/vvd", "s0", choice="Tegen", seats=30),
            _vote("v7", "factions/vvd", "s2", choice="Voor", seats=30),
        ]
    )
    return store


def test_the_list_newest_first_the_key_settling_a_day_undated_last(
    votes: GraphStore,
) -> None:
    page = get_decisions(votes)
    assert list(page) == ["total", "items", "facets"]
    assert page["total"] == 5
    assert _keys(page) == ["s0", "s1", "s2", "s4", "s3"]
    first = page["items"][1]
    assert json.dumps(first) == json.dumps(
        {
            "id": "decisions/s1",
            "key": "s1",
            "date": "2024-01-01",
            "subject": "Motie over de ÉCOLE",
            "display_name": "Motie 2024Z00001: Motie over de ÉCOLE",
            "external_id": "b1",
            "dossier_numbers": ["36000"],
            "kind": "Motie",
            "primary_case_kind": "Motie",
            "decision_kind": None,
            "passed": True,
            "chamber": "TK",
            "result": None,
            "method": None,
            "bill_decision": None,
            "vote_kind": None,
            "tally": {"Voor": 80, "Tegen": 70},
            "voters": {"Voor": 3, "Tegen": 2},
        }
    )
    # an empty chamber is no chamber: the first label of TK and EK; no tally is {}
    s0 = page["items"][0]
    assert (s0["chamber"], s0["tally"], s0["voters"]) == ("TK", {}, {})
    assert page["items"][2]["chamber"] == "EK"
    assert page["items"][4]["chamber"] is None


def test_the_facets_count_without_their_own_filter(votes: GraphStore) -> None:
    facets = get_decisions(votes)["facets"]
    assert list(facets) == ["kind", "passed", "days"]
    # by count, most first, then by value (null first)
    assert facets["kind"] == [
        {"value": "Motie", "count": 3},
        {"value": None, "count": 1},
        {"value": "Amendement", "count": 1},
    ]
    assert facets["passed"] == [
        {"value": False, "count": 2},
        {"value": True, "count": 2},
        {"value": None, "count": 1},
    ]
    assert facets["days"] == [
        {"date": None, "count": 1, "passed": 0},
        {"date": "2023-05-05", "count": 2, "passed": 1},
        {"date": "2024-01-01", "count": 2, "passed": 1},
    ]
    assert all(list(f) == ["value", "count"] for f in facets["kind"])
    assert all(list(d) == ["date", "count", "passed"] for d in facets["days"])

    motions = get_decisions(votes, DecisionFilters(kinds=("Motie",), passed=True))
    assert motions["total"] == 2 and _keys(motions) == ["s1", "s2"]
    # the kinds under the outcome filter, the outcomes under the kind filter
    assert motions["facets"]["kind"] == [{"value": "Motie", "count": 2}]
    assert motions["facets"]["passed"] == [
        {"value": True, "count": 2},
        {"value": False, "count": 1},
    ]
    assert motions["facets"]["days"] == [
        {"date": "2023-05-05", "count": 1, "passed": 1},
        {"date": "2024-01-01", "count": 1, "passed": 1},
    ]


@pytest.mark.parametrize(
    ("filters", "keys"),
    [
        (DecisionFilters(party="VVD"), ["s0", "s1", "s2"]),
        (DecisionFilters(party=" vvd ", choice="Voor"), ["s1", "s2"]),
        (DecisionFilters(party="nobody"), []),
        (DecisionFilters(chamber="ek"), ["s0", "s2"]),
        (DecisionFilters(dossier="36000"), ["s1"]),
        (DecisionFilters(date_from="2023-05-05"), ["s0", "s1", "s2", "s4"]),
        (DecisionFilters(date_to="2023-05-05"), ["s2", "s4"]),
        (DecisionFilters(date_from="2024-01-01", date_to="2024-01-01"), ["s0", "s1"]),
        # a part of the subject in any case, ASCII or not
        (DecisionFilters(q="école"), ["s1"]),
        (DecisionFilters(q="MOTIE"), ["s1", "s4"]),
        (DecisionFilters(kinds=("Amendement", "Motie")), ["s0", "s1", "s2", "s4"]),
        (DecisionFilters(passed=False), ["s0", "s4"]),
    ],
)
def test_the_filters(
    votes: GraphStore, filters: DecisionFilters, keys: list[str]
) -> None:
    page = get_decisions(votes, filters)
    assert _keys(page) == keys
    assert page["total"] == len(keys)


def test_the_pages(votes: GraphStore) -> None:
    assert _keys(get_decisions(votes, limit=2)) == ["s0", "s1"]
    second = get_decisions(votes, limit=2, offset=2)
    assert _keys(second) == ["s2", "s4"] and second["total"] == 5
    assert _keys(get_decisions(votes, limit=2, offset=4)) == ["s3"]
    beyond = get_decisions(votes, limit=2, offset=10)
    assert beyond["items"] == [] and beyond["total"] == 5
    assert beyond["facets"]["kind"][0] == {"value": "Motie", "count": 3}


def test_a_decision_with_its_votes(votes: GraphStore) -> None:
    detail = get_decision_detail(votes, "s1")
    assert detail is not None
    # MERGE(decision, {votes}): the keys of the document in byte order, then votes
    assert list(detail) == ["_id", "_key", "labels", "props", "type", "votes"]
    assert (detail["_id"], detail["labels"]) == ("decisions/s1", ["TK"])
    assert detail["props"]["tally"] == {"Voor": 80, "Tegen": 70}
    # the most seats first, then by name, then by key; no seats last; a voter that is
    # gone is left out
    assert json.dumps(detail["votes"]) == json.dumps(
        [
            {
                "voter_id": "factions/a",
                "voter_key": "a",
                "name": "B-partij",
                "choice": "Tegen",
                "seats": 40,
            },
            {
                "voter_id": "factions/x",
                "voter_key": "x",
                "name": "B-partij",
                "choice": "Tegen",
                "seats": 40,
            },
            {
                "voter_id": "factions/vvd",
                "voter_key": "vvd",
                "name": "VVD",
                "choice": "Voor",
                "seats": 30,
            },
            {
                "voter_id": "members/m1",
                "voter_key": "m1",
                "name": "Anna",
                "choice": "Voor",
                "seats": None,
            },
        ]
    )
    assert get_decision_detail(votes, "s3")["votes"] == []  # type: ignore[index]
    assert get_decision_detail(votes, "nope") is None


def test_the_document_a_decision_was_about(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "documents",
        [
            {"_key": k, "type": "document", "labels": [], "props": p}
            for k, p in (
                ("old", {"date": "2020-01-01", "title": "Oud"}),
                ("new", {"date": "2021-01-01"}),
                ("b", {"date": "2022-01-01"}),
                ("a", {"date": "2022-01-01"}),
                ("undated", {}),
            )
        ],
    )
    store.bulk_insert_or_update_edges(
        [
            _part_of("e1", "new", "c1"),
            _part_of("e2", "old", "c1"),
            _part_of("e3", "b", "c2"),
            _part_of("e4", "a", "c2"),
            _part_of("e5", "undated", "c3"),
            _part_of("e6", "new", "c3"),
            _part_of("e7", "missing", "c4"),
        ]
    )

    def document(**props: Any) -> str | None:
        found = get_decision_document(store, {"props": props})
        return found["_key"] if found else None

    # the primary case first; within a case the oldest, the key settling a day
    assert document(primary_case_id="c2", case_ids=["c1", "c2"]) == "a"
    assert document(case_ids=["c1", "c2"]) == "old"
    # no date sorts first, as null does
    assert document(case_ids=["c3"]) == "undated"
    # a case without documents, or with one that is gone, is passed over
    assert document(case_ids=["c4", "c9", "c1"]) == "old"
    assert document(case_ids=["c4"]) is None
    assert document() is None
    found = get_decision_document(store, {"props": {"case_ids": ["c1"]}})
    assert found == {
        "_key": "old",
        "_id": "documents/old",
        "type": "document",
        "labels": [],
        "props": {"date": "2020-01-01", "title": "Oud"},
    }


def test_the_votes_taken_on_a_document(store: GraphStore) -> None:
    # cases keyed as normalize keys them (make_node_key of the Zaak id); a motion (its own
    # case), a bill with a later paper of the same case, and a case
    # the decision does not name (another motion on the same agenda item)
    store.bulk_insert_or_update_nodes(
        "cases",
        [
            {"_key": k, "type": "case", "labels": [], "props": {"external_id": e}}
            for k, e in (("z_m", "Z-M"), ("z_b", "Z-B"), ("z_o", "Z-O"))
        ],
    )
    store.bulk_insert_or_update_nodes(
        "documents",
        [
            {"_key": k, "type": "document", "labels": [], "props": p}
            for k, p in (
                ("motie", {"date": "2026-09-01", "kind": "Motie"}),
                ("wet", {"date": "2026-01-01", "kind": "Voorstel van wet"}),
                ("nota", {"date": "2026-03-01", "kind": "Nota naar aanleiding"}),
                ("andere", {"date": "2026-09-01", "kind": "Motie"}),
            )
        ],
    )
    store.bulk_insert_or_update_nodes(
        "decisions",
        [
            _node("s_motie", date="2026-09-08", primary_case_id="Z-M", passed=True),
            _node("s_wet_1", date="2026-06-02", primary_case_id="Z-B", passed=True),
            _node("s_wet_0", date="2026-06-01", primary_case_id="Z-B", passed=False),
            # about both motions, naming the other one
            _node("s_andere", date="2026-09-08", primary_case_id="Z-O"),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "factions",
        [
            {
                "_key": "vvd",
                "type": "faction",
                "labels": [],
                "props": {"abbreviation": "VVD"},
            }
        ],
    )

    def about(key: str, decision: str, case: str) -> dict[str, Any]:
        return {
            "_key": key,
            "_from": f"decisions/{decision}",
            "_to": f"cases/{case}",
            "relation": "ABOUT",
            "source": "test",
        }

    store.bulk_insert_or_update_edges(
        [
            _part_of("p1", "motie", "z_m"),
            _part_of("p2", "wet", "z_b"),
            _part_of("p3", "nota", "z_b"),
            _part_of("p4", "andere", "z_o"),
            about("a1", "s_motie", "z_m"),
            about("a2", "s_wet_1", "z_b"),
            about("a3", "s_wet_0", "z_b"),
            about("a4", "s_andere", "z_m"),
            about("a5", "s_andere", "z_o"),
            _vote("v1", "factions/vvd", "s_motie", choice="Voor", seats=24),
        ]
    )

    def keys(document: str) -> list[str]:
        return [
            d["_key"] for d in get_document_decisions(store, f"documents/{document}")
        ]

    assert keys("motie") == ["s_motie"]
    assert keys("andere") == ["s_andere"]
    # the bill carries the votes on it, oldest first; a later paper of its case none
    assert keys("wet") == ["s_wet_0", "s_wet_1"]
    assert keys("nota") == []
    assert keys("missing") == []
    # a decision whose named case has no document takes the first of its other cases
    store.bulk_insert_or_update_nodes(
        "decisions",
        [
            _node(
                "s_leeg",
                date="2026-09-09",
                primary_case_id="Z-LEEG",
                case_ids=["Z-LEEG", "Z-O"],
            )
        ],
    )
    store.bulk_insert_or_update_edges([about("a6", "s_leeg", "z_o")])
    assert keys("andere") == ["s_andere", "s_leeg"]
    # with how each faction voted, as the decision detail gives it
    (motion,) = get_document_decisions(store, "documents/motie")
    assert motion["votes"][0]["voter_key"] == "vvd"
    assert motion["votes"][0]["choice"] == "Voor"
