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
    COLLECTION_EDGES,
    COLLECTION_MEMBERS,
    RELATION_VOTED,
)
from lawgraph.core import tk_records
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, make_node_key
from lawgraph.core.raw_records import payload_json
from lawgraph.core.tk_records import VoteCast
from lawgraph.db import EdgeWriter, NodeWriter, Store, make_edge_doc
from lawgraph.db.queries.normalize import edges as normalize_edges
from lawgraph.db.queries.normalize import tk as normalize_tk
from lawgraph.pipelines.normalize._tk_cases import link_node
from lawgraph.pipelines.normalize._tk_deleted import Deleted

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
    # the Stemming rows the Kamer deleted, and the Besluiten a row names deleted
    deleted: Deleted = field(default_factory=lambda: Deleted(COLLECTION_EDGES))
    struck: Deleted = field(
        default_factory=lambda: Deleted(COLLECTION_DECISIONS, tk_records.decision_key)
    )

    def drop_struck(self) -> None:
        """Leave out the decisions whose Besluit the Kamer deleted, also those whose rows
        were read before the row or record that struck them."""
        for decision_id in self.struck.ids:
            self.by_decision.pop(decision_id, None)
            self.decisions.pop(decision_id, None)


def read_votes(raw_records: Iterable[dict[str, Any]]) -> Votes:
    """Group the Stemming rows by ``Besluit_Id``; a deleted row, and every row of a
    deleted Besluit, is no vote."""
    votes = Votes()
    for raw in raw_records:
        votes.rows += 1
        payload = payload_json(raw)
        if votes.deleted(payload) or _struck(votes, payload):
            continue
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
    votes.drop_struck()
    return votes


def _struck(votes: Votes, payload: dict[str, Any]) -> bool:
    """Whether the Besluit the row *payload* votes on is one the Kamer deleted."""
    decision = payload.get("Besluit")
    return isinstance(decision, dict) and votes.struck(decision)


def merge_votes(votes: Votes, more: Votes) -> None:
    """Add the rows of *more* to *votes*, for the decisions *votes* has none of."""
    for decision_id, casts in more.by_decision.items():
        if decision_id not in votes.by_decision:
            votes.by_decision[decision_id] = casts
            votes.decisions[decision_id] = more.decisions.get(decision_id, {})
    votes.faction_labels |= more.faction_labels
    votes.rows += more.rows


def add_decisions(votes: Votes, payloads: Iterable[dict[str, Any]]) -> int:
    """Add the Besluit records no vote row carries (a hamerstuk: ``Stemmen - zonder
    stemming aannemen``) as decisions without votes; one with votes keeps the Besluit its
    rows carry. How many were added."""
    added = 0
    for payload in payloads:
        decision_id = str(payload.get("Id") or "")
        if not decision_id or tk_records.is_deleted(payload):
            continue
        if decision_id not in votes.by_decision:
            votes.by_decision[decision_id] = []
            votes.decisions[decision_id] = payload
            added += 1
    return added


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


def remove_deleted_votes(
    store: Store, votes: Votes, decision_nodes: dict[str, Node]
) -> None:
    """What the Kamer deleted of the votes goes: the VOTED edge of a deleted Stemming, a
    decision whose Besluit it deleted, and a decision no live vote is left on, with their
    edges. The rows of every decision a deleted vote was on are read (``fetch_raw``), so
    a decision this run did not write has none."""
    voted_on = {
        row["key"]
        for row in normalize_tk.decisions_of_vote_records(
            store, sorted(votes.deleted.ids)
        )
    }
    edges = votes.deleted.remove(store)
    empty = sorted(voted_on - {node.key for node in decision_nodes.values()})
    removed = normalize_edges.remove_nodes(store, COLLECTION_DECISIONS, empty)
    removed += votes.struck.remove(store)
    logger.info("Removed %d votes and %d decisions the Kamer deleted.", edges, removed)


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
    lost: dict[str, list[str]] = {}  # decision -> the voters no node was found for
    written: dict[str, list[str]] = {}  # decision node -> the keys of its VOTED edges
    for decision_id, votes in votes_by_decision.items():
        decision_node = decision_nodes.get(decision_id)
        if decision_node is None or not decision_node.node_id:
            continue
        roll_call = decision_node.props.get("vote_kind") == tk_records.VOTE_KIND_MEMBER
        keys = written.setdefault(decision_node.node_id, [])
        for cast in votes:
            voter = _voter_id(cast, faction_nodes, known_members, roll_call=roll_call)
            if voter is None:
                if not roll_call and cast.seats:
                    lost.setdefault(decision_id, []).append(cast.faction_label)
                continue
            edge = _vote_edge(cast, voter, decision_node.node_id, source=source)
            keys.append(edge["_key"])
            writer.add_doc(edge)
    writer.flush()
    removed = _remove_other_votes(store, written)
    logger.info(
        "Wrote %d VOTED edges; removed %d no live vote gives.", writer.added, removed
    )
    _report_lost_votes(lost)


def _vote_edge(
    cast: VoteCast, voter: str, decision_id: str, *, source: str
) -> dict[str, Any]:
    """The VOTED edge of *cast*, carrying the choice, its weight and the Stemming it is
    made of."""
    return make_edge_doc(
        voter,
        decision_id,
        RELATION_VOTED,
        source=source,
        meta={
            "choice": cast.choice,
            "seats": cast.seats,
            "record_ids": [cast.record_id] if cast.record_id else [],
        },
    )


# Decisions whose other VOTED edges are removed in one query.
_DECISION_CHUNK = 500


def _remove_other_votes(store: Store, written: dict[str, list[str]]) -> int:
    """Remove the VOTED edges into the decisions of *written* that this run did not write:
    a decision is its live rows together, all read, so an edge no row gives (a vote the
    Kamer deleted, a voter the graph no longer holds) goes."""
    decisions = sorted(written)
    removed = 0
    for start in range(0, len(decisions), _DECISION_CHUNK):
        chunk = decisions[start : start + _DECISION_CHUNK]
        keep = [key for decision in chunk for key in written[decision]]
        removed += normalize_edges.remove_edges_into_except(
            store, RELATION_VOTED, chunk, keep
        )
    return removed


def _report_lost_votes(lost: dict[str, list[str]]) -> None:
    """Warn when the votes of a decision do not add up to its tally: a faction vote whose
    Fractie the graph does not hold is left out of ``votes[]``, not of the tally."""
    if not lost:
        return
    labels = sorted({label or "?" for voters in lost.values() for label in voters})
    logger.warning(
        "%d decisions have faction votes without a faction node, so their votes do not "
        "add up to the tally; the factions: %s.",
        len(lost),
        ", ".join(labels),
    )


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
    return faction.node_id if faction else None
