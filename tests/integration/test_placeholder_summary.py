"""A placeholder inhoudsindicatie ("kopje volgt") is no summary (J16), also on a judgment an
earlier run gave it to: the real ``normalize rechtspraak`` clears it."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    COLLECTION_JUDGMENTS,
)
from lawgraph.core.models import make_node_key
from lawgraph.db import GraphStore
from tests.integration.seed import rechtspraak_xml, write_judgments

ECLI = "ECLI:NL:GHAMS:2026:2678"


def test_a_placeholder_summary_an_earlier_run_stored_is_cleared(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    xml = rechtspraak_xml(
        ECLI, "Gerechtshof Amsterdam", "2026-09-22", "200.343.062/01"
    ).replace(
        "<uitspraak>",
        "<inhoudsindicatie><para>kopje volgt</para></inhoudsindicatie><uitspraak>",
    )
    write_judgments(store, {ECLI: xml})
    key = make_node_key(ECLI)
    store.bulk_insert_or_update_nodes(
        COLLECTION_JUDGMENTS,
        [
            {
                "key": key,
                "type": "judgment",
                "labels": [],
                "props": {"summary": "kopje volgt"},
            }
        ],
    )

    cli("normalize", "rechtspraak")

    judgment = store.get_node(COLLECTION_JUDGMENTS, key)
    assert judgment is not None and judgment.props.get("summary") is None
