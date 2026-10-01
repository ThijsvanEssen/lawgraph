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
    assert _counts(body["facets"]["kind"]) == {"Motie": 6, "Wetgeving": 2}
    assert {row["kind"] for row in body["items"]} == {"Motie", "Wetgeving"}
    bills = _get(store, "/api/decisions", kind="Wetgeving")
    assert bills["total"] == 2
    assert _counts(bills["facets"]["kind"]) == {"Motie": 6, "Wetgeving": 2}


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
        _decision("d1", "Motie", True, "2025-03-04", "Motie over de wegen"),
        _decision("d2", "Motie", False, "2025-03-04", "Motie over het spoor"),
        _decision("d3", "Amendement", True, "2025-03-11", "Amendement over WEGEN"),
        _decision("d4", "Wetgeving", True, "2025-03-18", "Wijziging Wegenwet"),
        _decision("d5", "Motie", False, "2025-04-01", "Motie over water"),
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
        {"value": "Motie", "count": 3},
        {"value": "Amendement", "count": 1},
        {"value": "Wetgeving", "count": 1},
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
    motions = _get(store, "/api/decisions", kind="Motie", passed="false", limit=1)
    assert motions["total"] == 2 and len(motions["items"]) == 1
    assert _counts(motions["facets"]["kind"]) == {"Motie": 2}
    assert _counts(motions["facets"]["passed"]) == {True: 1, False: 2}
    assert motions["facets"]["days"] == [
        {"date": "2025-03-04", "count": 1, "passed": 0},
        {"date": "2025-04-01", "count": 1, "passed": 0},
    ]
    both = _get(store, "/api/decisions", kind="Motie,Amendement")
    assert both["total"] == 4

    march = _get(store, "/api/decisions", **{"from": "2025-03-05", "to": "2025-03-31"})
    assert [row["key"] for row in march["items"]] == ["d4", "d3"]

    wegen = _get(store, "/api/decisions", q="Wegen")
    assert {row["key"] for row in wegen["items"]} == {"d1", "d3", "d4"}

    voted = _get(store, "/api/decisions", party="f1")
    assert voted["total"] == 4
    against = _get(store, "/api/decisions", party="f1", vote="tegen")
    assert {row["key"] for row in against["items"]} == {"d2", "d4"}
    assert _counts(against["facets"]["kind"]) == {"Motie": 1, "Wetgeving": 1}


# ── judgments ────────────────────────────────────────────────────────────────


def _judgment(
    number: int,
    tier: str,
    court: str,
    date: str | None,
    subjects: list[str],
    court_kind: str | None = None,
    source: str = "rechtspraak",
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
            "source": source,
            "tier": tier,
            "court_kind": court_kind or tier,
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
        _judgment(
            6,
            "andere_instantie",
            "AGAMS",
            "1990-03-01",
            ["Bestuursrecht"],
            court_kind="ambtenarengerecht",
        ),
        _judgment(
            7,
            "andere_instantie",
            "RVBAMS",
            "1990-04-01",
            ["Bestuursrecht"],
            court_kind="raad_van_beroep",
        ),
    ]
    with NodeWriter(store) as writer:
        writer.add_all(nodes)


def test_the_judgments_carry_their_subjects_and_are_counted_per_tier_and_year(
    database: str,
) -> None:
    store = ArangoStore()
    _build_judgments(store)

    everything = _get(store, "/api/judgments")
    assert everything["total"] == 7
    assert everything["facets"]["tier"] == [
        {"value": "andere_instantie", "count": 2},
        {"value": "hoge_raad", "count": 2},
        {"value": "rechtbank", "count": 2},
        {"value": "gerechtshof", "count": 1},
    ]
    assert everything["facets"]["year"] == [
        {"value": None, "count": 1},
        {"value": "1990", "count": 2},
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
    # the kinds of court within a tier; another tier drops the kind chosen
    other = _get(
        store, "/api/judgments", tier="andere_instantie", court_kind="raad_van_beroep"
    )
    assert [row["key"] for row in other["items"]] == ["j7"]
    assert other["items"][0]["court_kind"] == "raad_van_beroep"
    assert _counts(other["facets"]["court_kind"]) == {
        "ambtenarengerecht": 1,
        "raad_van_beroep": 1,
    }
    assert _counts(other["facets"]["tier"])["hoge_raad"] == 2
    in_2024 = _get(store, "/api/judgments", **{"from": "2024-01-01"})
    assert _counts(in_2024["facets"]["tier"]) == {"hoge_raad": 1, "rechtbank": 2}
    assert _counts(in_2024["facets"]["year"]) == {
        None: 1,
        "1990": 2,
        "2023": 1,
        "2024": 3,
    }


def test_the_judgments_are_counted_per_source_without_the_source_filter(
    database: str,
) -> None:
    store = ArangoStore()
    _build_judgments(store)
    with NodeWriter(store) as writer:
        writer.add_all(
            [
                _judgment(6, "ehrm", "ECHR", "2024-03-01", [], source="echr"),
                _judgment(7, "ehrm", "ECHR", "2023-03-01", [], source="echr"),
            ]
        )

    everything = _get(store, "/api/judgments")
    assert everything["facets"]["source"] == [
        {"value": "rechtspraak", "count": 5},
        {"value": "echr", "count": 2},
    ]
    # one call gives the page of one source and the total of the other
    dutch = _get(store, "/api/judgments", source="rechtspraak", limit=1)
    assert dutch["total"] == 5 and len(dutch["items"]) == 1
    assert _counts(dutch["facets"]["source"]) == {"rechtspraak": 5, "echr": 2}
    assert _counts(dutch["facets"]["tier"]) == {
        "hoge_raad": 2,
        "rechtbank": 2,
        "gerechtshof": 1,
    }
    # the facet keeps the other filters
    in_2024 = _get(store, "/api/judgments", **{"from": "2024-01-01"})
    assert _counts(in_2024["facets"]["source"]) == {"rechtspraak": 3, "echr": 1}
