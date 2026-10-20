"""How current the graph is, per source (``data_as_of`` in ``/api/stats`` and the feed): when
its newest raw record was fetched, the date of its newest dated record, never one after
today (a planned paper, a law coming into force next year), and what the last run did with
it (``completeness.source``)."""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    CHAMBER_TK,
    COLLECTION_DOCUMENTS,
    COLLECTION_JUDGMENTS,
    RAW_KIND_RECHTSPRAAK_CONTENT,
    RAW_KIND_TK_DOCUMENT,
    SOURCE_ECHR,
    SOURCE_RECHTSPRAAK,
    SOURCE_TK,
)
from lawgraph.core.completeness import SOURCE_RUN_STATE
from lawgraph.db import GraphStore, RawSourceWriter, raw_source_doc
from lawgraph.db.queries import state as state_queries
from lawgraph.sources.addresses import GRAPH, SOURCES

TODAY = dt.date.today()
LATER = (TODAY + dt.timedelta(days=30)).isoformat()


def _node(collection: str, key: str, labels: list[str], **props: Any) -> dict[str, Any]:
    return {
        "key": key,
        "type": collection.rstrip("s"),
        "labels": labels,
        "props": props,
    }


def _seed(store: GraphStore) -> None:
    with RawSourceWriter(store) as writer:
        for source, kind, key in (
            (SOURCE_TK, RAW_KIND_TK_DOCUMENT, "d1"),
            (SOURCE_RECHTSPRAAK, RAW_KIND_RECHTSPRAAK_CONTENT, "ECLI:NL:HR:2026:1"),
        ):
            writer.add(
                raw_source_doc(
                    source=source, kind=kind, external_id=key, payload_text="x"
                )
            )
    store.bulk_insert_or_update_nodes(
        COLLECTION_DOCUMENTS,
        [
            _node(COLLECTION_DOCUMENTS, "d1", [CHAMBER_TK], date="2026-09-01"),
            _node(COLLECTION_DOCUMENTS, "d2", [CHAMBER_TK], date="2026-09-20"),
            _node(COLLECTION_DOCUMENTS, "planned", [CHAMBER_TK], date=LATER),
        ],
    )
    store.bulk_insert_or_update_nodes(
        COLLECTION_JUDGMENTS,
        [
            _node(
                COLLECTION_JUDGMENTS, "j1", [], date="2026-09-23", date_eff="2026-09-23"
            ),
            _node(COLLECTION_JUDGMENTS, "stub", [], stub=True),
        ],
    )


def test_each_source_says_how_current_it_is(store: GraphStore) -> None:
    _seed(store)
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        stats = client.get("/api/stats").json()["data_as_of"]
        feed = client.get("/api/feed").json()["data_as_of"]
    finally:
        app.dependency_overrides.pop(get_store, None)

    assert set(stats) == set(SOURCES) - {GRAPH}  # each source, fetched from or not
    assert stats[SOURCE_TK]["newest"] == "2026-09-20"  # not the planned paper
    assert stats[SOURCE_RECHTSPRAAK]["newest"] == "2026-09-23"
    assert stats[SOURCE_TK]["retrieved_at"].startswith(TODAY.isoformat()[:4])
    assert feed == stats


def test_each_source_says_what_the_last_run_did_with_it(store: GraphStore) -> None:
    _seed(store)
    state_queries.set_state(
        store,
        SOURCE_RUN_STATE + SOURCE_ECHR,
        {"state": "paused", "at": "2026-10-20T03:00:00Z", "as_of": None},
    )
    state_queries.set_state(
        store,
        SOURCE_RUN_STATE + SOURCE_RECHTSPRAAK,
        {"state": "unavailable", "at": "2026-10-20T03:00:00Z", "as_of": "2026-10-19"},
    )
    app.dependency_overrides[get_store] = lambda: store
    try:
        stats = TestClient(app).get("/api/stats").json()["data_as_of"]
    finally:
        app.dependency_overrides.pop(get_store, None)

    def source(name: str) -> dict[str, Any]:
        return stats[name]["completeness"]["source"]

    assert source(SOURCE_ECHR) == {"state": "paused", "as_of": None, "missing": None}
    assert source(SOURCE_RECHTSPRAAK)["state"] == "unavailable"
    assert source(SOURCE_RECHTSPRAAK)["as_of"] == "2026-10-19"
    # no run recorded yet: done as of its newest fetched record
    assert source(SOURCE_TK) == {
        "state": "done",
        "as_of": stats[SOURCE_TK]["retrieved_at"],
        "missing": None,
    }
    assert source("kiesraad") == {"state": "pending", "as_of": None, "missing": None}
