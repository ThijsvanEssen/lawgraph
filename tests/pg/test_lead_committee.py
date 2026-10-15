"""An activity led by two committees names the same one, the first by key, wherever it is
shown: its own page, the timeline of its dossier and the next activity of that dossier."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import RELATION_ABOUT, RELATION_LED_BY
from lawgraph.core.dossier_stages import ACTIVITY_PLANNED
from lawgraph.db import GraphStore, make_edge_doc
from lawgraph.db.queries.activities import get_activity
from lawgraph.db.queries.dossiers import get_dossier_timeline, get_next_activity


def _node(key: str, node_type: str, **props: Any) -> dict[str, Any]:
    return {"key": key, "type": node_type, "labels": [], "props": props}


def test_an_activity_led_by_two_committees_names_the_first(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "dossiers", [_node("d1", "dossier", number="36000")]
    )
    store.bulk_insert_or_update_nodes(
        "activities",
        [
            _node(
                "a1",
                "activity",
                kind="Commissiedebat",
                date="2099-01-01",
                status=ACTIVITY_PLANNED,
            )
        ],
    )
    store.bulk_insert_or_update_nodes(
        "committees",
        [
            _node("vws", "committee", name="Volksgezondheid", slug="vws"),
            _node("bzk", "committee", name="Binnenlandse Zaken", slug="bzk"),
        ],
    )
    store.bulk_insert_or_update_edges(
        [
            make_edge_doc("activities/a1", "dossiers/d1", RELATION_ABOUT, source="t"),
            make_edge_doc(
                "activities/a1", "committees/vws", RELATION_LED_BY, source="t"
            ),
            make_edge_doc(
                "activities/a1", "committees/bzk", RELATION_LED_BY, source="t"
            ),
        ]
    )
    first = {"key": "bzk", "slug": "bzk", "name": "Binnenlandse Zaken"}

    activity = get_activity(store, "a1")
    assert activity is not None and activity["committee"] == first
    (entry,) = get_dossier_timeline(store, "dossiers/d1")
    assert entry["committee"] == first
    upcoming = get_next_activity(store, "dossiers/d1", "2026-10-14")
    assert upcoming is not None and upcoming["committee"] == first
