"""Decisions and the votes cast on them.

TK returns one Stemming row per voter per Besluit. The rows are grouped into
one Decision node per Besluit; each row then becomes a VOTED edge — from the
member on a roll-call (``Hoofdelijk``), from the faction otherwise.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_DECISIONS,
    COLLECTION_MEMBERS,
    RELATION_VOTED,
)
from lawgraph.core import tk_records
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, make_node_key
from lawgraph.core.raw_records import payload_json
from lawgraph.core.tk_records import VoteCast
from lawgraph.db import EdgeWriter, NodeWriter, Store
from lawgraph.pipelines.normalize._tk_cases import link_node

logger = get_logger(__name__)


@dataclass
class Votes:
    """What one walk over the Stemming rows yields (190K rows for two years: read once)."""

    by_decision: dict[str, list[VoteCast]] = field(default_factory=dict)
    # The expanded Besluit rides along on every row; the first that carries it is kept.
    decisions: dict[str, dict[str, Any]] = field(default_factory=dict)
    faction_labels: set[str] = field(
        default_factory=set
    )  # every ``ActorFractie`` spelling
    rows: int = 0


def read_votes(raw_records: Iterable[dict[str, Any]]) -> Votes:
    """Group the Stemming rows by ``Besluit_Id``."""
    votes = Votes()
    for raw in raw_records:
        votes.rows += 1
        payload = payload_json(raw)
        label = (payload.get("ActorFractie") or "").strip()
        if label:
            votes.faction_labels.add(label)
        cast = tk_records.vote(payload)
        if cast is None:
            continue
        votes.by_decision.setdefault(cast.decision_id, []).append(cast)
        decision = payload.get("Besluit")
        if isinstance(decision, dict) and cast.decision_id not in votes.decisions:
            votes.decisions[cast.decision_id] = decision
    return votes


def normalize_decisions(store: Store, votes: Votes) -> dict[str, Node]:
    """Decision nodes, keyed by TK ``Besluit_Id``."""
    nodes: dict[str, Node] = {}
    for decision_id, casts in votes.by_decision.items():
        key, props = tk_records.decision(
            decision_id, votes.decisions.get(decision_id, {}), casts
        )
        nodes[decision_id] = Node(
            collection=COLLECTION_DECISIONS,
            type=NodeType.DECISION,
            key=key,
            labels=["TK"],
            props=props,
        )

    with NodeWriter(store) as writer:
        writer.add_all(nodes.values())

    logger.info("Normalized %d decisions from %d vote rows.", len(nodes), votes.rows)
    return {decision_id: link_node(node) for decision_id, node in nodes.items()}


def link_votes(
    store: Store,
    votes_by_decision: dict[str, list[VoteCast]],
    decision_nodes: dict[str, Node],
    faction_nodes: dict[str, Node],
    *,
    source: str,
) -> None:
    """VOTED edges into each decision, carrying the choice and its weight.

    A roll-call names every member, so its edges start at members and the
    faction rows are left out — the party of the day follows from the
    member's faction membership.
    """
    known_members = store.existing_keys(
        COLLECTION_MEMBERS,
        {
            make_node_key(cast.person_id)
            for votes in votes_by_decision.values()
            for cast in votes
            if cast.person_id
        },
    )

    writer = EdgeWriter(store, what="VOTED edges")
    for decision_id, votes in votes_by_decision.items():
        decision_node = decision_nodes.get(decision_id)
        if decision_node is None:
            continue
        roll_call = decision_node.props.get("vote_kind") == tk_records.VOTE_KIND_MEMBER
        for cast in votes:
            voter = _voter_id(cast, faction_nodes, known_members, roll_call=roll_call)
            writer.add(
                voter,
                decision_node.arango_id,
                RELATION_VOTED,
                source=source,
                meta={"choice": cast.choice, "seats": cast.seats},
            )
    writer.flush()
    logger.info("Wrote %d VOTED edges.", writer.added)


def _voter_id(
    cast: VoteCast,
    faction_nodes: dict[str, Node],
    known_members: set[str],
    *,
    roll_call: bool,
) -> str | None:
    if roll_call:
        if not cast.person_id:
            return None
        key = make_node_key(cast.person_id)
        return f"{COLLECTION_MEMBERS}/{key}" if key in known_members else None
    faction = faction_nodes.get(cast.faction_id or "")
    return faction.arango_id if faction else None
