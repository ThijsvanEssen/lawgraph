"""``ops/usage-counts.py`` on a real PostgreSQL: its read-only session is enough for
``load_notation_parser``, and the laws of the graph decide what a term is."""

from __future__ import annotations

import importlib.util
from types import ModuleType

import psycopg
from psycopg.rows import dict_row

from lawgraph.db import GraphStore
from lawgraph.db.queries.search.parser import load_notation_parser
from tests.paths import ROOT


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "usage_counts", ROOT / "ops" / "usage-counts.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_terms_are_read_by_the_laws_in_a_read_only_session(
    store: GraphStore, database_url: str
) -> None:
    usage = _load()
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            {
                "key": "bwbr0001",
                "type": "instrument",
                "labels": [],
                "props": {
                    "bwb_id": "BWBR0001",
                    "citation_title": "Wet milieubeheer",
                    "short_title": "Wm",
                },
            }
        ],
    )
    with psycopg.connect(
        database_url,
        options="-c default_transaction_read_only=on",
        row_factory=dict_row,
    ) as conn:
        parser = load_notation_parser(usage._ReadOnlyStore(conn))
    assert usage.term_kind(parser, "art. 5 wm") == usage.CITATION
    assert usage.term_kind(parser, "wet milieubeheer") == usage.LAW_NAME
    assert usage.term_kind(parser, "ontslag") == usage.FREE_TEXT
