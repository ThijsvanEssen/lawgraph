"""The neighbours the API derives on read, which no edge holds (``RelationSpec.derived``).

A dossier is ``LED_BY`` the committees that lead an activity about it (``ABOUT`` it, or a
case ``PART_OF`` it), as the ``committees`` of ``GET /api/dossiers/{number}``; a committee has
those dossiers the other way round, from the activities it leads as ``lg_led`` keeps them
(``ABOUT`` a dossier). Each neighbour comes with an edge of its own: key
``derived:<from>:LED_BY:<to>``, status ``canoniek``, ``meta`` ``derived_from``
(``activities``), ``role`` (``lead``: the Kamer names a voortouwcommissie alone) and
``activities`` (how many of them the committee leads).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ACTIVITIES,
    COLLECTION_COMMITTEES,
    COLLECTION_DOSSIERS,
    EDGE_STATUS_CANONIEK,
    RELATION_ABOUT,
    RELATION_LED_BY,
    RELATION_PART_OF,
)
from lawgraph.core.models import Direction
from lawgraph.db import GraphStore
from lawgraph.db._rows import (
    canvas_edge_doc,
    canvas_props,
    light_edge_doc,
    light_node_doc,
    light_props,
)
from lawgraph.db.queries.dossiers import LEAD_COMMITTEE_CTES

# What a derived edge is derived from, in its ``meta``.
DERIVED_FROM_ACTIVITIES = "activities"
# The role of a committee that leads an activity (``Voortouwcommissie``).
ROLE_LEAD = "lead"

# The committees of a dossier: ``other`` and ``activities``.
_COMMITTEES_OF_DOSSIER = f"""
WITH {LEAD_COMMITTEE_CTES}
SELECT l.id AS other, l.led AS activities
FROM lead_ids l
WHERE split_part(l.id, '/', 1) = '{COLLECTION_COMMITTEES}'
"""

# The dossiers of a committee: those of the activities it leads, kept in ``lg_led``, a range
# of its index (``lg_led_committee``, which includes the dossiers).
_DOSSIERS_OF_COMMITTEE = f"""
SELECT x.dossier_id AS other, count(*)::int AS activities
FROM lg_led l CROSS JOIN LATERAL unnest(l.dossiers) AS x(dossier_id)
WHERE l.committee_id = %(node_id)s AND l.item_collection = '{COLLECTION_ACTIVITIES}'
GROUP BY 1
"""


@dataclass(frozen=True)
class DerivedBucket:
    """A bucket of derived neighbours of a node of collection ``of``."""

    of: str
    direction: Direction
    collection: str
    statement: str

    def edge(self, node_id: str, other: str, activities: int) -> dict[str, Any]:
        """The derived edge between the node and its neighbour *other*."""
        from_id, to_id = (
            (node_id, other) if self.direction == "outbound" else (other, node_id)
        )
        return {
            "key": f"derived:{from_id}:{RELATION_LED_BY}:{to_id}",
            "from_id": from_id,
            "to_id": to_id,
            "doc": {
                "relation": RELATION_LED_BY,
                "status": EDGE_STATUS_CANONIEK,
                "meta": {
                    "derived_from": DERIVED_FROM_ACTIVITIES,
                    "role": ROLE_LEAD,
                    "activities": activities,
                },
            },
        }


DERIVED_BUCKETS: tuple[DerivedBucket, ...] = (
    DerivedBucket(
        COLLECTION_DOSSIERS, "outbound", COLLECTION_COMMITTEES, _COMMITTEES_OF_DOSSIER
    ),
    DerivedBucket(
        COLLECTION_COMMITTEES, "inbound", COLLECTION_DOSSIERS, _DOSSIERS_OF_COMMITTEE
    ),
)


@dataclass
class DerivedPage:
    """A derived bucket: how many neighbours, and the page asked for as ``(neighbour,
    edge)``."""

    bucket: DerivedBucket
    total: int
    entries: list[tuple[dict[str, Any], dict[str, Any]]]


def derived_pages(
    store: GraphStore,
    collection: str,
    node_id: str,
    wanted: Callable[[DerivedBucket], bool],
    *,
    limit: int,
    offset: int,
    canvas: bool = False,
    importance: bool = False,
) -> list[DerivedPage]:
    """The derived buckets of the node *node_id* of *collection* that *wanted* lets
    through, each with ``limit`` neighbours from ``offset``: in the order of their ids,
    with *importance* the most activities first. A bucket without neighbours is left out."""
    pages = []
    for bucket in DERIVED_BUCKETS:
        if bucket.of != collection or not wanted(bucket):
            continue
        rows = store.query(
            bucket.statement,
            {
                "node_id": node_id,
                "dossier_id": node_id,
                "about": RELATION_ABOUT,
                "led_by": RELATION_LED_BY,
                "part_of": RELATION_PART_OF,
            },
        )
        found = {row["other"]: row["activities"] for row in rows}
        if not found:
            continue
        order = sorted(found, key=lambda o: (-found[o], o) if importance else ("", o))
        page = order[offset : offset + limit]
        nodes = _nodes(store, bucket.collection, page, canvas)
        edge_doc = canvas_edge_doc if canvas else light_edge_doc
        entries = [
            (nodes[other], edge_doc(bucket.edge(node_id, other, found[other])))
            for other in page
            if other in nodes
        ]
        pages.append(DerivedPage(bucket, len(found), entries))
    return pages


def _nodes(
    store: GraphStore, collection: str, ids: list[str], canvas: bool
) -> dict[str, dict[str, Any]]:
    """The nodes of *collection* with these ids by id, as a neighbour has them."""
    if not ids:
        return {}
    props = canvas_props("n") if canvas else light_props("n")
    rows = store.query(
        f"""
        SELECT n.id, n.key, n.type, n.labels, {props} AS props
        FROM nodes n
        WHERE n.id = ANY(%(ids)s) AND n.collection = '{collection}'
        """,
        {"ids": ids},
    )
    return {row["id"]: light_node_doc(row) for row in rows}
