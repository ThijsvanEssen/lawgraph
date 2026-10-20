"""``semantic graph-derive``: the derived columns of a table computed again from ``props``,
after a release changed how they are derived; and the digest per table of that derivation in
``pipeline_state``, which tells when a table needs it (``db/queries/derive.py``)."""

from __future__ import annotations

import logging
from typing import Any

from lawgraph.db import GraphStore
from lawgraph.db.queries import derive
from lawgraph.db.queries import state as state_queries
from lawgraph.db.schema import DERIVE_STATE, derive_digest, derived_collections
from lawgraph.pipelines.semantic.graph_derive import GraphDeriveSemanticPipeline


def _dossier(number: str) -> dict[str, Any]:
    return {
        "key": number,
        "type": "dossier",
        "labels": [],
        "props": {"number": number, "opened_on": f"2020-01-{number[-2:]}"},
    }


NUMBERS = [f"360{n:02d}" for n in range(1, 8)]


def _stale(store: GraphStore) -> None:
    """Every dossier with a derived ``number`` its props do not give: what rows written
    under an older derivation hold. Writing the column alone fires no trigger."""
    store.bulk_insert_or_update_nodes("dossiers", [_dossier(n) for n in NUMBERS])
    store.execute("UPDATE dossiers SET number = 'old', opened_on = NULL")


def _numbers(store: GraphStore) -> list[str]:
    return list(store.query("SELECT number FROM dossiers ORDER BY id"))


def test_a_run_derives_every_row_again_in_batches(
    store: GraphStore, monkeypatch
) -> None:
    _stale(store)
    monkeypatch.setattr(derive, "BATCH", 3)  # three statements
    result = GraphDeriveSemanticPipeline(store, collection="dossiers").run()
    assert result.updated == len(NUMBERS)
    assert _numbers(store) == NUMBERS
    assert list(
        store.query("SELECT count(*) FROM dossiers WHERE opened_on IS NULL")
    ) == [0]


def test_slices_go_on_where_the_last_one_ended(store: GraphStore, caplog) -> None:
    """``--limit`` stops after that many rows and the log names the last; ``--after`` starts
    past it. The digest is kept once a series of slices from the start reaches the end."""
    _stale(store)
    key = DERIVE_STATE + "dossiers"
    state_queries.set_state(store, key, {"digest": "older"})
    assert derive.stale_collections(store) == ["dossiers"]

    caplog.set_level(logging.INFO)
    first = GraphDeriveSemanticPipeline(store, collection="dossiers", limit=4).run()
    assert first.updated == 4
    assert "go on with --after dossiers/36004" in caplog.text
    assert _numbers(store) == NUMBERS[:4] + ["old"] * 3
    assert derive.stale_collections(store) == ["dossiers"]

    rest = GraphDeriveSemanticPipeline(
        store, collection="dossiers", after="dossiers/36004", limit=4
    ).run()
    assert rest.updated == 3
    assert _numbers(store) == NUMBERS
    assert derive.stale_collections(store) == []
    assert state_queries.get_state(store, key) == {"digest": derive_digest("dossiers")}


def test_a_slice_not_from_the_start_keeps_the_digest(store: GraphStore) -> None:
    """Rows before ``--after`` were not derived again by this series: still stale."""
    _stale(store)
    state_queries.set_state(store, DERIVE_STATE + "dossiers", {"digest": "older"})
    GraphDeriveSemanticPipeline(
        store, collection="dossiers", after="dossiers/36004"
    ).run()
    assert _numbers(store) == ["old"] * 4 + NUMBERS[4:]
    assert derive.stale_collections(store) == ["dossiers"]


def test_without_a_table_it_names_those_that_need_it(store: GraphStore, caplog) -> None:
    _stale(store)
    state_queries.set_state(store, DERIVE_STATE + "dossiers", {"digest": "older"})
    caplog.set_level(logging.WARNING)
    result = GraphDeriveSemanticPipeline(store).run()
    assert result.updated == 0
    assert _numbers(store) == ["old"] * len(NUMBERS)
    assert "lawgraph semantic graph-derive dossiers" in caplog.text


def test_a_new_database_holds_the_digest_of_every_derivation(store: GraphStore) -> None:
    """The schema keeps the digest of a table it creates, and leaves one already kept: a
    table derived otherwise stays stale until ``graph-derive`` ran over it."""
    kept = state_queries.states_starting_with(store, DERIVE_STATE)
    assert kept == {
        DERIVE_STATE + c: {"digest": derive_digest(c)} for c in derived_collections()
    }
    assert derive.stale_collections(store) == []


def test_the_api_start_warns_of_a_stale_derivation(store: GraphStore, caplog) -> None:
    from lawgraph.api import app as api_app

    state_queries.set_state(store, DERIVE_STATE + "judgments", {"digest": "older"})
    caplog.set_level(logging.WARNING)
    api_app._warn_of_stale_derivations(store)
    assert (
        "The derivation of judgments changed: run `lawgraph semantic graph-derive "
        "judgments`" in caplog.text
    )
