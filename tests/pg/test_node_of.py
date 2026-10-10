"""``schema.node_of``: the node an id names, read from its own table only (the view
``nodes`` joined on an id looked in every table of the graph, an index probe each)."""

from __future__ import annotations

import json
from typing import Any

from lawgraph.db import GraphStore
from lawgraph.db.schema import NODE_COLLECTIONS, node_of


def _executed(plan: dict[str, Any], found: set[str]) -> set[str]:
    """The tables the plan read at least once (``Actual Loops`` above 0)."""
    if "Relation Name" in plan and plan.get("Actual Loops", 0) > 0:
        found.add(plan["Relation Name"])
    for child in plan.get("Plans", []):
        _executed(child, found)
    return found


def test_a_node_is_read_from_its_own_table_alone(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "documents",
        [{"_key": "d1", "type": "document", "labels": [], "props": {"title": "Brief"}}],
    )
    store.bulk_insert_or_update_nodes(
        "dossiers",
        [
            {
                "_key": "36600",
                "type": "dossier",
                "labels": [],
                "props": {"number": "36600"},
            }
        ],
    )
    store.bulk_insert_or_update_edges(
        [
            {
                "_key": "e1",
                "_from": "documents/d1",
                "_to": "dossiers/36600",
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
    with store.pool.connection() as conn:
        (plan,) = conn.execute("EXPLAIN (ANALYZE, FORMAT JSON) " + statement).fetchone()
    plan = plan if isinstance(plan, list) else json.loads(plan)
    read = _executed(plan[0]["Plan"], set())
    assert read == {"edges", "documents"}, read
    assert len(NODE_COLLECTIONS) > 10  # the others were not looked in
