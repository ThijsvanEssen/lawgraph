"""People in parliament: committees, members, factions and their memberships.

Every function here takes the raw TK records for one entity and returns the
nodes it wrote, keyed by the TK identifier the other builders join on. Reads
and writes are bulk: one existence lookup per collection, one edge flush.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_COMMITTEES,
    COLLECTION_FACTIONS,
    COLLECTION_MEMBERS,
    RELATION_MEMBER_OF,
)
from lawgraph.core import tk_records
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, make_node_key
from lawgraph.core.raw_records import payload_json
from lawgraph.db import EdgeWriter, NodeWriter, Store

logger = get_logger(__name__)


def normalize_committees(
    store: Store, raw_records: Iterable[dict[str, Any]]
) -> dict[str, Node]:
    """Commissie nodes, keyed by TK ``Id``."""
    nodes: dict[str, Node] = {}
    for raw in raw_records:
        parsed = tk_records.committee(payload_json(raw))
        if parsed is None:
            continue
        key, props = parsed
        nodes[props["external_id"]] = Node(
            collection=COLLECTION_COMMITTEES,
            type=NodeType.COMMITTEE,
            key=key,
            labels=["TK"],
            props=props,
        )
    _write(store, nodes.values())
    logger.info("Normalized %d committees.", len(nodes))
    return nodes


def normalize_members(
    store: Store, raw_records: Iterable[dict[str, Any]]
) -> dict[str, Node]:
    """Persoon nodes, keyed by TK ``Id``."""
    nodes: dict[str, Node] = {}
    for raw in raw_records:
        parsed = tk_records.member(payload_json(raw))
        if parsed is None:
            continue
        key, props = parsed
        nodes[props["external_id"]] = Node(
            collection=COLLECTION_MEMBERS,
            type=NodeType.MEMBER,
            key=key,
            labels=["TK"],
            props=props,
        )
    _write(store, nodes.values())
    logger.info("Normalized %d members.", len(nodes))
    return nodes


def normalize_factions(
    store: Store,
    faction_raws: Iterable[dict[str, Any]],
    vote_labels: set[str],
) -> dict[str, Node]:
    """Faction nodes, by the TK ``Id`` of every Fractie record.

    Several records can share one abbreviation: a faction that returns gets a fresh record
    (50PLUS 2012-2021 and from 2025, Krol, Van Kooten-Arissen), and the Kamer names either
    one on votes and seats, the old one also on a vote of today. They are one faction: one
    node, whose props come from the seated (else the latest changed) record and whose
    period spans them all, reached by the id of each of them. *vote_labels* are the
    spellings votes use for a faction (``Stemming.ActorFractie``).
    """
    by_key: dict[str, list[dict[str, Any]]] = {}
    for raw in faction_raws:
        payload = payload_json(raw)
        label = tk_records.faction_label(payload)
        if label:
            by_key.setdefault(make_node_key(label), []).append(payload)

    nodes: dict[str, Node] = {}
    for records in by_key.values():
        current = max(records, key=tk_records.faction_is_current)
        parsed = tk_records.faction(
            current, tk_records.faction_aliases(current, vote_labels), records
        )
        if parsed is None:
            continue
        key, props = parsed
        node = Node(
            collection=COLLECTION_FACTIONS,
            type=NodeType.FACTION,
            key=key,
            labels=["TK"],
            props=props,
        )
        for external_id in props["external_ids"]:
            nodes[external_id] = node
    written = {node.key: node for node in nodes.values()}
    _write(store, written.values())
    logger.info(
        "Normalized %d factions (%d Fractie records).", len(written), len(nodes)
    )
    return nodes


def link_members_to_committees(
    store: Store,
    committee_raws: Iterable[dict[str, Any]],
    *,
    source: str,
) -> None:
    """MEMBER_OF edges from Persoon to Commissie, with the seat's period."""
    seats = [
        (
            make_node_key(str(payload.get("Id") or "")),
            tk_records.committee_seats(payload),
        )
        for payload in (payload_json(raw) for raw in committee_raws)
    ]
    known_committees = store.existing_keys(
        COLLECTION_COMMITTEES, {key for key, _ in seats}
    )
    known_members = store.existing_keys(
        COLLECTION_MEMBERS,
        {make_node_key(pid) for _, held in seats for pid in held},
    )

    writer = EdgeWriter(store, what="committee seat edges")
    for committee_key, held in seats:
        if committee_key not in known_committees:
            continue
        for person_id, periods in held.items():
            member_key = make_node_key(person_id)
            if member_key not in known_members:
                continue
            writer.add(
                f"{COLLECTION_MEMBERS}/{member_key}",
                f"{COLLECTION_COMMITTEES}/{committee_key}",
                RELATION_MEMBER_OF,
                source=source,
                meta=tk_records.representative_period(periods) or None,
            )
    writer.flush()
    logger.info("Linked %d members to committees.", writer.added)


def link_members_to_factions(
    store: Store,
    seat_raws: Iterable[dict[str, Any]],
    member_nodes: dict[str, Node],
    faction_nodes: dict[str, Node],
    *,
    source: str,
) -> None:
    """MEMBER_OF edges from Persoon to Fractie, plus the member's timeline.

    The edge key is deterministic per (member, faction), so someone who left
    and rejoined a party has one edge carrying the latest period; the full
    timeline is denormalised onto the member as ``faction_memberships`` so a
    profile renders without a traversal.
    """
    writer = EdgeWriter(store, what="faction seat edges")
    timeline: dict[str, list[dict[str, Any]]] = {}

    for raw in seat_raws:
        parsed = tk_records.seat_holding(payload_json(raw))
        if parsed is None:
            continue
        person_id, faction_id, period = parsed
        member_node = member_nodes.get(person_id)
        faction_node = faction_nodes.get(faction_id)
        if not (member_node and faction_node):
            continue

        writer.add(
            member_node.arango_id,
            faction_node.arango_id,
            RELATION_MEMBER_OF,
            source=source,
            meta=period,
        )
        timeline.setdefault(person_id, []).append(
            {
                "faction_id": faction_node.arango_id,
                "faction_key": faction_node.key,
                "name": faction_node.props.get("name"),
                "abbreviation": faction_node.props.get("abbreviation"),
                "aliases": faction_node.props.get("aliases") or [],
                **period,
            }
        )

    writer.flush()
    _write_timelines(store, member_nodes, timeline)
    logger.info(
        "Linked %d members to factions (%d with a timeline).",
        writer.added,
        len(timeline),
    )


def _write_timelines(
    store: Store,
    member_nodes: dict[str, Node],
    timeline: dict[str, list[dict[str, Any]]],
) -> None:
    """Store each member's sorted faction timeline and their current party."""
    updated: list[dict[str, Any]] = []
    for person_id, memberships in timeline.items():
        node = member_nodes.get(person_id)
        if node is None:
            continue
        memberships.sort(
            key=lambda m: (m["from_date"] or "", m["to_date"] or "9999-12-31")
        )
        node.props["faction_memberships"] = memberships
        current = next(
            (m for m in reversed(memberships) if not m["to_date"]), memberships[-1]
        )
        party = current["abbreviation"] or current["name"]
        name = node.props.get("name") or ""
        node.props["party"] = party
        node.props["display_name"] = (
            f"{name} ({party})" if name and party else (name or party or "")
        )
        updated.append(node.to_document())
    if updated:
        store.bulk_insert_or_update_nodes(COLLECTION_MEMBERS, updated)


def _write(store: Store, nodes: Any) -> None:
    with NodeWriter(store) as writer:
        writer.add_all(nodes)
