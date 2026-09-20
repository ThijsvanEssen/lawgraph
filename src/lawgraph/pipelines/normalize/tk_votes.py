"""Decisions and the votes cast on them.

TK returns one Stemming row per voter per Besluit. The rows are grouped into
one Decision node per Besluit; each row then becomes a VOTED edge — from the
member on a roll-call (``Hoofdelijk``), from the faction otherwise.
"""

from __future__ import annotations

from collections.abc import Iterable
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
from lawgraph.db import ArangoStore, EdgeWriter, NodeWriter
from lawgraph.pipelines.normalize.tk_cases import link_node

logger = get_logger(__name__)


def read_votes(
    raw_records: Iterable[dict[str, Any]],
) -> dict[str, list[VoteCast]]:
    """Group the Stemming rows by ``Besluit_Id``."""
    by_decision: dict[str, list[VoteCast]] = {}
    for raw in raw_records:
        cast = tk_records.vote(payload_json(raw))
        if cast is not None:
            by_decision.setdefault(cast.decision_id, []).append(cast)
    return by_decision


def normalize_decisions(
    store: ArangoStore,
    raw_records: Iterable[dict[str, Any]],
    votes_by_decision: dict[str, list[VoteCast]],
) -> dict[str, Node]:
    """Decision nodes, keyed by TK ``Besluit_Id``.

    The expanded Besluit rides along on every Stemming row of the decision;
    the first one that carries it describes the whole group.
    """
    decisions: dict[str, dict[str, Any]] = {}
    rows = 0
    for raw in raw_records:
        rows += 1
        payload = payload_json(raw)
        decision_id = str(payload.get("Besluit_Id") or "")
        decision = payload.get("Besluit")
        if decision_id and isinstance(decision, dict) and decision_id not in decisions:
            decisions[decision_id] = decision

    nodes: dict[str, Node] = {}
    for decision_id, votes in votes_by_decision.items():
        key, props = tk_records.decision(
            decision_id, decisions.get(decision_id, {}), votes
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

    logger.info("Normalized %d decisions from %d vote rows.", len(nodes), rows)
    return {decision_id: link_node(node) for decision_id, node in nodes.items()}


def link_votes(
    store: ArangoStore,
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

    writer = EdgeWriter(store)
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
