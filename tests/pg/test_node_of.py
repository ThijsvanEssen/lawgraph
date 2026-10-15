"""``schema.node_of``: the node an id names, read from its own table only (the view
``nodes`` joined on an id looked in every table of the graph, an index probe each)."""

from __future__ import annotations

from typing import Any

from lawgraph.db import GraphStore
from lawgraph.db.schema import NODE_COLLECTIONS, node_of
from tests.pg.plans import explain, plan_nodes


def _executed(plan: dict[str, Any], found: set[str]) -> set[str]:
    """The tables the plan read at least once (``Actual Loops`` above 0)."""
    return found | {
        n["Relation Name"]
        for n in plan_nodes(plan)
        if "Relation Name" in n and n.get("Actual Loops", 0) > 0
    }


def test_a_node_is_read_from_its_own_table_alone(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "documents",
        [{"key": "d1", "type": "document", "labels": [], "props": {"title": "Brief"}}],
    )
    store.bulk_insert_or_update_nodes(
        "dossiers",
        [
            {
                "key": "36600",
                "type": "dossier",
                "labels": [],
                "props": {"number": "36600"},
            }
        ],
    )
    store.bulk_insert_or_update_edges(
        [
            {
                "key": "e1",
                "from_id": "documents/d1",
                "to_id": "dossiers/36600",
                "relation": "PART_OF",
                "source": "tk",
            }
        ]
    )
    statement = f"""
        SELECT n.collection, n.key, n.props ->> 'title' AS title
        FROM edges e CROSS JOIN {node_of("e.from_id", "e.from_collection")} n
        WHERE e.to_id = 'dossiers/36600'
        """
    assert list(store.query(statement)) == [
        {"collection": "documents", "key": "d1", "title": "Brief"}
    ]
    read = _executed(explain(store, statement, analyze=True), set())
    assert read == {"edges", "documents"}, read
    assert len(NODE_COLLECTIONS) > 10  # the others were not looked in
