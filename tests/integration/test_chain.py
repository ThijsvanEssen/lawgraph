"""The chain as it is run: seed raw records, ``normalize all``, ``semantic all``, ``check``."""

from __future__ import annotations

from typing import Any

from lawgraph.commands.check import check
from lawgraph.db import ArangoStore
from tests.integration.seed import seed

COLLECTIONS = (
    "cases",
    "documents",
    "dossiers",
    "decisions",
    "activities",
    "commitments",
    "members",
    "factions",
    "committees",
    "instruments",
    "articles",
    "judgments",
    "edges",
)


def _counts(store: ArangoStore) -> dict[str, int]:
    return {name: store.db.collection(name).count() for name in COLLECTIONS}


def _edge_keys(store: ArangoStore) -> set[str]:
    return set(store.query("FOR e IN edges RETURN e._key"))


def test_the_whole_chain_runs_and_a_second_run_changes_nothing(
    database: str, cli: Any
) -> None:
    store = ArangoStore()
    seed(store, documents=500, judgments=100, regulations=20)

    cli("normalize", "all")
    cli("semantic", "all")
    first, first_edges = _counts(store), _edge_keys(store)

    # Every part of the model came out of it, with the edges between them.
    assert first["cases"] == 500 and first["documents"] == 500
    assert first["judgments"] >= 100 and first["instruments"] >= 20
    assert all(first[name] > 0 for name in COLLECTIONS), first

    # The judgment linkers read the XML from raw_sources (it is not kept on the node): every
    # judgment cites the next one and two articles.
    linked = "FOR e IN edges FILTER STARTS_WITH(e._from, 'judgments/') RETURN e._to"
    targets = list(store.query(linked))
    assert sum(t.startswith("judgments/") for t in targets) >= 100
    assert any(t.startswith("articles/") for t in targets)
    sample = store.db.collection("judgments").random()
    assert "raw_xml" not in sample["props"]

    # Idempotent: the same input again is the same graph, not a second copy of it.
    cli("normalize", "all")
    cli("semantic", "all")
    assert _counts(store) == first
    assert _edge_keys(store) == first_edges

    report = check(store)
    assert [p for p in report.problems if not p.startswith("raw ")] == []


def test_check_says_when_a_source_was_retrieved_and_never_normalized(
    database: str,
) -> None:
    store = ArangoStore()
    seed(store, documents=20, judgments=5, regulations=2)

    problems = check(store).problems
    assert any("tk:" in p and "no node in cases" in p for p in problems)
    assert any("rechtspraak:" in p and "no node in judgments" in p for p in problems)
    # A kind of the registry that was never retrieved is a problem too (tk-zaak was, for weeks).
    assert any(p.startswith("raw staatscourant/") for p in problems)


def test_check_says_when_normalize_is_behind(database: str, cli: Any) -> None:
    """38,577 judgments retrieved and 7,442 normalized looked like a healthy database."""
    store = ArangoStore()
    seed(store, documents=20, judgments=5, regulations=2)
    cli("normalize", "rechtspraak")
    assert not [p for p in check(store, edges=False).problems if "is behind" in p]

    seed(store, documents=20, judgments=60, regulations=2)  # 55 more arrive
    behind = [p for p in check(store, edges=False).problems if "is behind" in p]
    assert behind and behind[0].startswith(
        "rechtspraak: 60 rs-content records and 5 nodes"
    )


def test_check_finds_an_edge_without_its_node(database: str, cli: Any) -> None:
    store = ArangoStore()
    seed(store, documents=50, judgments=5, regulations=2)
    cli("normalize", "all")
    assert not [p for p in check(store).problems if p.startswith("edges")]

    victim = next(iter(store.query("FOR e IN edges LIMIT 1 RETURN e._to")))
    collection, key = victim.split("/")
    store.db.collection(collection).delete(key)
    assert [p for p in check(store).problems if p.startswith("edges")]
