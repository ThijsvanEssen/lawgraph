"""A placeholder inhoudsindicatie ("kopje volgt") is no summary (J16), also on a judgment an
earlier run gave it to: the real ``normalize rechtspraak`` clears it."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    COLLECTION_JUDGMENTS,
    RAW_KIND_RS_CONTENT,
    SOURCE_RECHTSPRAAK,
)
from lawgraph.core.models import make_node_key
from lawgraph.db import GraphStore, RawSourceWriter, raw_source_doc
from tests.integration.test_judgment_relations import _xml

ECLI = "ECLI:NL:GHAMS:2026:2678"


def test_a_placeholder_summary_an_earlier_run_stored_is_cleared(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    xml = _xml(ECLI, "Gerechtshof Amsterdam", "2026-09-22", "200.343.062/01").replace(
        "<uitspraak>",
        "<inhoudsindicatie><para>kopje volgt</para></inhoudsindicatie><uitspraak>",
    )
    with RawSourceWriter(store) as writer:
        writer.add(
            raw_source_doc(
                source=SOURCE_RECHTSPRAAK,
                kind=RAW_KIND_RS_CONTENT,
                external_id=ECLI,
                payload_text=xml,
                meta={"ecli": ECLI},
            )
        )
    key = make_node_key(ECLI)
    store.bulk_insert_or_update_nodes(
        COLLECTION_JUDGMENTS,
        [
            {
                "_key": key,
                "type": "judgment",
                "labels": [],
                "props": {"summary": "kopje volgt"},
            }
        ],
    )

    cli("normalize", "rechtspraak")

    judgment = store.get_node(COLLECTION_JUDGMENTS, key)
    assert judgment is not None and judgment.props.get("summary") is None
