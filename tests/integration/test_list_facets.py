"""The facets of the decision and judgment lists, counted for real, and from an index."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    COLLECTION_DECISIONS,
    COLLECTION_FACTIONS,
    COLLECTION_JUDGMENTS,
    RELATION_VOTED,
)
from lawgraph.core.models import Node, NodeType
from lawgraph.db import ArangoStore, EdgeWriter, NodeWriter
from lawgraph.db.queries.judgments import JudgmentFilters, get_judgments_list
from tests.integration.seed import seed


def _get(store: ArangoStore, path: str, **params: Any) -> dict[str, Any]:
    app.dependency_overrides[get_store] = lambda: store
    try:
        response = TestClient(app).get(path, params=params)
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200, response.text
    return response.json()


def _counts(facet: list[dict[str, Any]]) -> dict[Any, int]:
    return {bucket["value"]: bucket["count"] for bucket in facet}


# ── decisions ────────────────────────────────────────────────────────────────


def test_normalize_stores_the_kind_of_the_case_a_decision_decided(
    database: str, cli: Any
) -> None:
    store = ArangoStore()
    # 96 votes in 8 Besluiten; Besluit 0 and 7 decide a Wetgeving, the others a Motie
    seed(store, documents=96, judgments=0, regulations=0)
    cli("normalize", "tk-dossiers")

    body = _get(store, "/api/decisions", limit=200)
    assert body["total"] == 8
    assert _counts(body["facets"]["kind"]) == {"motie": 6, "wetsvoorstel": 2}
    assert {row["kind"] for row in body["items"]} == {"motie", "wetsvoorstel"}
    bills = _get(store, "/api/decisions", kind="wetsvoorstel")
    assert bills["total"] == 2
    assert _counts(bills["facets"]["kind"]) == {"motie": 6, "wetsvoorstel": 2}


def _decision(key: str, kind: str, passed: bool, date: str, subject: str) -> Node:
    return Node(
        collection=COLLECTION_DECISIONS,
        type=NodeType.DECISION,
        key=key,
        labels=["TK"],
        props={
            "decision_id": key,
            "kind": kind,
            "passed": passed,
            "date": date,
            "subject": subject,
            "dossier_numbers": ["36000"],
            "tally": {"Voor": 80, "Tegen": 70},
        },
    )


def _build_decisions(store: ArangoStore) -> None:
    nodes = [
        _decision("d1", "motie", True, "2025-03-04", "Motie over de wegen"),
        _decision("d2", "motie", False, "2025-03-04", "Motie over het spoor"),
        _decision("d3", "amendement", True, "2025-03-11", "Amendement over WEGEN"),
        _decision("d4", "wetsvoorstel", True, "2025-03-18", "Wijziging Wegenwet"),
        _decision("d5", "motie", False, "2025-04-01", "Motie over water"),
        Node(
            collection=COLLECTION_FACTIONS,
            type=NodeType.FACTION,
            key="f1",
            labels=["TK"],
            props={"name": "F1"},
        ),
    ]
    with NodeWriter(store) as writer:
        writer.add_all(nodes)
    edges = EdgeWriter(store, what=None)
    for key, choice in [
        ("d1", "Voor"),
        ("d2", "Tegen"),
        ("d3", "Voor"),
        ("d4", "Tegen"),
    ]:
        edges.add(
            f"{COLLECTION_FACTIONS}/f1",
            f"{COLLECTION_DECISIONS}/{key}",
            RELATION_VOTED,
            source="test",
            meta={"choice": choice, "seats": 10},
        )
    edges.flush()


def test_the_decisions_are_filtered_and_counted_per_kind_outcome_and_day(
    database: str,
) -> None:
    store = ArangoStore()
    _build_decisions(store)

    everything = _get(store, "/api/decisions")
    assert everything["total"] == 5
    assert everything["facets"]["kind"] == [
        {"value": "motie", "count": 3},
        {"value": "amendement", "count": 1},
        {"value": "wetsvoorstel", "count": 1},
    ]
    assert _counts(everything["facets"]["passed"]) == {True: 3, False: 2}
    assert everything["facets"]["days"] == [
        {"date": "2025-03-04", "count": 2, "passed": 1},
        {"date": "2025-03-11", "count": 1, "passed": 1},
        {"date": "2025-03-18", "count": 1, "passed": 1},
        {"date": "2025-04-01", "count": 1, "passed": 0},
    ]

    # kind is counted without the kind filter, passed without the passed filter, the
    # days under both; total is the matches, whatever the limit
    motions = _get(store, "/api/decisions", kind="motie", passed="false", limit=1)
    assert motions["total"] == 2 and len(motions["items"]) == 1
    assert _counts(motions["facets"]["kind"]) == {"motie": 2}
    assert _counts(motions["facets"]["passed"]) == {True: 1, False: 2}
    assert motions["facets"]["days"] == [
        {"date": "2025-03-04", "count": 1, "passed": 0},
        {"date": "2025-04-01", "count": 1, "passed": 0},
    ]
    both = _get(store, "/api/decisions", kind="motie,amendement")
    assert both["total"] == 4

    march = _get(store, "/api/decisions", **{"from": "2025-03-05", "to": "2025-03-31"})
    assert [row["key"] for row in march["items"]] == ["d4", "d3"]

    wegen = _get(store, "/api/decisions", q="Wegen")
    assert {row["key"] for row in wegen["items"]} == {"d1", "d3", "d4"}

    voted = _get(store, "/api/decisions", party="f1")
    assert voted["total"] == 4
    against = _get(store, "/api/decisions", party="f1", vote="tegen")
    assert {row["key"] for row in against["items"]} == {"d2", "d4"}
    assert _counts(against["facets"]["kind"]) == {"motie": 1, "wetsvoorstel": 1}


# ── judgments ────────────────────────────────────────────────────────────────


def _judgment(
    number: int, tier: str, court: str, date: str | None, subjects: list[str]
) -> Node:
    ecli = f"ECLI:NL:{court}:2020:{number}"
    return Node(
        collection=COLLECTION_JUDGMENTS,
        type=NodeType.JUDGMENT,
        key=f"j{number}",
        labels=["Rechtspraak"],
        props={
            "ecli": ecli,
            "display_name": ecli,
            "source": "rechtspraak",
            "tier": tier,
            "court_code": court,
            "date_eff": date,
            "subjects": subjects,
            "summary": "Samenvatting. " * 200,
            "inbound_citation_count": number,
        },
    )


def _build_judgments(store: ArangoStore) -> None:
    nodes = [
        _judgment(1, "hoge_raad", "HR", "2023-05-01", ["Strafrecht"]),
        _judgment(2, "hoge_raad", "HR", "2024-02-01", ["Civiel recht"]),
        _judgment(3, "rechtbank", "RBAMS", "2024-06-01", ["Strafrecht"]),
        _judgment(
            4,
            "rechtbank",
            "RBAMS",
            "2024-07-01",
            ["Bestuursrecht; Belastingrecht", "Strafrecht"],
        ),
        _judgment(5, "gerechtshof", "GHAMS", None, ["Bestuursrecht"]),
    ]
    with NodeWriter(store) as writer:
        writer.add_all(nodes)


def test_the_judgments_carry_their_subjects_and_are_counted_per_tier_and_year(
    database: str,
) -> None:
    store = ArangoStore()
    _build_judgments(store)

    everything = _get(store, "/api/judgments")
    assert everything["total"] == 5
    assert everything["facets"]["tier"] == [
        {"value": "hoge_raad", "count": 2},
        {"value": "rechtbank", "count": 2},
        {"value": "gerechtshof", "count": 1},
    ]
    assert everything["facets"]["year"] == [
        {"value": None, "count": 1},
        {"value": "2023", "count": 1},
        {"value": "2024", "count": 3},
    ]
    by_key = {row["key"]: row for row in everything["items"]}
    assert by_key["j4"]["subjects"] == ["Bestuursrecht; Belastingrecht", "Strafrecht"]

    criminal = _get(store, "/api/judgments", subject="Strafrecht")
    assert {row["key"] for row in criminal["items"]} == {"j1", "j3", "j4"}
    # tier ignores the tier filter, year ignores from and to; both keep the others
    narrowed = _get(
        store,
        "/api/judgments",
        subject="Strafrecht",
        tier="rechtbank",
        **{"from": "2024-01-01"},
    )
    assert narrowed["total"] == 2
    assert _counts(narrowed["facets"]["tier"]) == {"rechtbank": 2}
    assert _counts(narrowed["facets"]["year"]) == {"2024": 2}
    in_2024 = _get(store, "/api/judgments", **{"from": "2024-01-01"})
    assert _counts(in_2024["facets"]["tier"]) == {"hoge_raad": 1, "rechtbank": 2}
    assert _counts(in_2024["facets"]["year"]) == {None: 1, "2023": 1, "2024": 3}


def _plans(store: ArangoStore, filters: JudgmentFilters) -> dict[str, list[dict]]:
    """The plan of every count of the list query, by the name of its LET."""
    captured: list[tuple[str, dict[str, Any]]] = []

    class Capture:
        def query(self, aql: str, bind_vars: dict[str, Any]) -> list[Any]:
            captured.append((aql, bind_vars))
            return []

    get_judgments_list(Capture(), filters)  # type: ignore[arg-type]
    aql, bind_vars = captured[0]
    # each facet on its own: the same loop, returning its count
    plans: dict[str, list[dict]] = {}
    for name in ("by_tier", "by_year"):
        body = aql.split(f"LET {name} = (", 1)[1].split("\n    )", 1)[0]
        used = {k: v for k, v in bind_vars.items() if f"@{k}" in body}
        plans[name] = store.db.aql.explain(body, bind_vars=used)["nodes"]
    return plans


def test_the_judgment_facets_read_an_index_and_no_judgment(database: str) -> None:
    """On the full database there are millions of judgments, each with its text: a facet
    that reads them takes minutes; one that walks an index, seconds at most."""
    store = ArangoStore()
    _build_judgments(store)

    for filters in (
        JudgmentFilters(),
        JudgmentFilters(tier="rechtbank"),
        JudgmentFilters(date_from="2024-01-01", date_to="2024-12-31"),
        JudgmentFilters(court="RBAMS"),
        JudgmentFilters(court="RBAMS", tier="rechtbank", date_from="2024-01-01"),
        JudgmentFilters(source="rechtspraak"),
    ):
        for name, nodes in _plans(store, filters).items():
            kinds = [node["type"] for node in nodes]
            assert "EnumerateCollectionNode" not in kinds, (filters, name, kinds)
            assert "MaterializeNode" not in kinds, (filters, name, kinds)
            index = next(node for node in nodes if node["type"] == "IndexNode")
            assert index.get("indexCoversProjections"), (filters, name, index)

    # an area of law is found through its array index, not by reading every judgment
    for name, nodes in _plans(store, JudgmentFilters(subject="Strafrecht")).items():
        kinds = [node["type"] for node in nodes]
        assert "EnumerateCollectionNode" not in kinds, (name, kinds)
