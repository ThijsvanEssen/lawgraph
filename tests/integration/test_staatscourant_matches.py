"""The Staatscourant regulations and the instruments they explain, as the queries of
``semantic staatscourant`` find them on the test server.

A regulation is matched by its BWB id, else by the citation title of an instrument its
title contains; one match per regulation, also when its title names two laws. With a date,
only the regulations of that date or later: ``props.date`` is a date, so a regulation of
that same day is in.
"""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    COLLECTION_DOCUMENTS,
    COLLECTION_INSTRUMENTS,
    SOURCE_STAATSCOURANT,
)
from lawgraph.core.models import NodeType
from lawgraph.db import ArangoStore
from lawgraph.db.queries.semantic import bwb as semantic_bwb

TEXT = "Deze regeling berust op de Wet op de proeven (BWBR0000001). " * 3


def _node(key: str, node_type: NodeType, **props: Any) -> dict[str, Any]:
    return {"_key": key, "type": node_type.value, "labels": [], "props": props}


def _publication(key: str, date: str, **props: Any) -> dict[str, Any]:
    return _node(
        key, NodeType.DOCUMENT, source=SOURCE_STAATSCOURANT, date=date, **props
    )


def _seed(store: ArangoStore) -> None:
    store.bulk_insert_or_update_nodes(
        COLLECTION_INSTRUMENTS,
        [
            _node(
                "bwbr0000001",
                NodeType.INSTRUMENT,
                bwb_id="BWBR0000001",
                citation_title="Wet op de proeven",
            ),
            _node(
                "bwbr0000002",
                NodeType.INSTRUMENT,
                bwb_id="BWBR0000002",
                citation_title="Wet op de toetsen",
            ),
        ],
    )
    store.bulk_insert_or_update_nodes(
        COLLECTION_DOCUMENTS,
        [
            _publication("stcrt-1", "2026-09-19", bwb_id="BWBR0000001", text=TEXT),
            _publication("stcrt-2", "2026-09-20", bwb_id="BWBR0000001"),
            # no BWB id; the title names both laws
            _publication(
                "stcrt-3",
                "2026-09-19",
                title="Regeling tot wijziging van de Wet op de proeven en de Wet op de toetsen",
            ),
            _publication("stcrt-4", "2026-09-18", bwb_id="BWBR0000002", text=TEXT),
            _publication("stcrt-5", "2026-09-19", bwb_id="BWBR0009999"),
        ],
    )


def _matches(store: ArangoStore, since_date: str | None) -> dict[str, dict[str, Any]]:
    rows = semantic_bwb.staatscourant_instrument_matches(store, since_date)
    by_publication = {row["pub_key"]: row for row in rows}
    assert len(by_publication) == len(rows)  # one row per publication
    return by_publication


def test_every_regulation_is_matched_once(database: str) -> None:
    store = ArangoStore()
    _seed(store)

    matches = _matches(store, None)

    assert {key: row["match_type"] for key, row in matches.items()} == {
        "stcrt-1": "bwb_id",
        "stcrt-2": "bwb_id",
        "stcrt-3": "title",
        "stcrt-4": "bwb_id",
    }
    assert matches["stcrt-2"]["inst_id"] == f"{COLLECTION_INSTRUMENTS}/bwbr0000001"
    assert matches["stcrt-4"]["inst_key"] == "bwbr0000002"
    assert matches["stcrt-3"]["inst_key"] in {"bwbr0000001", "bwbr0000002"}
    assert matches["stcrt-1"]["pub_id"] == f"{COLLECTION_DOCUMENTS}/stcrt-1"


def test_a_date_keeps_the_regulations_of_that_day_and_later(database: str) -> None:
    store = ArangoStore()
    _seed(store)

    assert set(_matches(store, "2026-09-19")) == {"stcrt-1", "stcrt-2", "stcrt-3"}
    texts = semantic_bwb.staatscourant_texts(store, "2026-09-19")
    assert [row["pub_key"] for row in texts] == ["stcrt-1"]
    everything = semantic_bwb.staatscourant_texts(store, None)
    assert sorted(row["pub_key"] for row in everything) == ["stcrt-1", "stcrt-4"]
