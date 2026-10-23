"""Semantic pipeline: the ministries as nodes of the graph, and what leads to them.

Every ministry name of ``data/ministries.json`` (``core.ministries``, from TOOI and the
Rijksoverheid) is a node ``ministries/<key>`` with its periods; a name that followed
another ``CONTINUES`` it. A regulation, a dossier and a commitment whose ``ministry`` names
one is ``LED_BY`` it (the regulation's from its WTI, ``normalize bwb``; the others from
``semantic tk-government``), and a member who held a post under one ``SERVED_IN`` it, with
those posts (``meta.posts``; ``normalize rijksoverheid``). Derived in full on every run:
what is no longer derived goes.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_MINISTRIES,
    RELATION_CONTINUES,
    RELATION_LED_BY,
    RELATION_SERVED_IN,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.ministries import MINISTRIES, MINISTRY_BY_KEY, Ministry
from lawgraph.core.models import Node, PipelineResult, node_id
from lawgraph.db import EdgeWriter, NodeWriter
from lawgraph.db.queries.removals import remove_nodes_except
from lawgraph.db.queries.semantic import tooi as semantic_tooi
from lawgraph.sources.addresses import edge_source

from .base import SemanticPipelineBase

logger = get_logger(__name__)

EDGE_SOURCE = edge_source(__name__)
RELATIONS = (RELATION_CONTINUES, RELATION_LED_BY, RELATION_SERVED_IN)


def ministry_props(ministry: Ministry) -> dict[str, Any]:
    """The props of the node of *ministry*."""
    return {
        "name": ministry.name,
        "display_name": ministry.name,
        "abbreviation": ministry.abbreviation,
        "tooi": ministry.tooi,
        "periods": [
            {
                "from_date": p.from_date,
                "to_date": p.to_date,
                "successor": p.successor,
                "basis": p.basis,
                "source": p.source,
                "successor_source": p.successor_source,
            }
            for p in ministry.periods
        ],
        "successor": ministry.successor,
        "to_date": ministry.to_date,
    }


class TooiMinistriesSemanticPipeline(SemanticPipelineBase):
    """Write the ministries and the edges into them."""

    def run(self) -> PipelineResult:
        result = PipelineResult()
        with NodeWriter(self.store) as nodes:
            for ministry in MINISTRIES:
                nodes.add(
                    Node(
                        collection=COLLECTION_MINISTRIES,
                        key=ministry.key,
                        labels=["TOOI"],
                        props=ministry_props(ministry),
                    )
                )
        remove_nodes_except(
            self.store, COLLECTION_MINISTRIES, [m.key for m in MINISTRIES]
        )
        edges = EdgeWriter(self.store, what=None, remembers=True)
        for ministry in MINISTRIES:
            for period in ministry.periods:
                if period.successor in MINISTRY_BY_KEY:
                    edges.add(
                        _ministry(period.successor),
                        _ministry(ministry.key),
                        RELATION_CONTINUES,
                        source=EDGE_SOURCE,
                    )
        led = 0
        for row in self._track(semantic_tooi.ministry_leads(self.store), "leads"):
            if row["ministry"] in MINISTRY_BY_KEY:
                led += edges.add(
                    row["id"],
                    _ministry(row["ministry"]),
                    RELATION_LED_BY,
                    source=EDGE_SOURCE,
                )
        posts: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in semantic_tooi.ministry_posts(self.store):
            post = row["post"]
            if post.get("ministry") in MINISTRY_BY_KEY:
                posts[(row["id"], post["ministry"])].append(post)
        for (member, key), held in posts.items():
            edges.add(
                member,
                _ministry(key),
                RELATION_SERVED_IN,
                source=EDGE_SOURCE,
                meta={"posts": held},
            )
        edges.flush_into(result)
        removed = sum(
            edges.remove_stale_of_source(relation, EDGE_SOURCE)
            for relation in RELATIONS
        )
        logger.info(
            "%d ministries: %d nodes lead to one, %d members served under one; removed "
            "%d edges no longer derived.",
            len(MINISTRIES),
            led,
            len({member for member, _ in posts}),
            removed,
        )
        return result


def _ministry(key: str) -> str:
    return node_id(COLLECTION_MINISTRIES, key)
