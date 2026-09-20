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
from lawgraph.db import ArangoStore, EdgeWriter, NodeWriter

logger = get_logger(__name__)


def normalize_committees(
    store: ArangoStore, raw_records: Iterable[dict[str, Any]]
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
    store: ArangoStore, raw_records: Iterable[dict[str, Any]]
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
    store: ArangoStore,
    faction_raws: list[dict[str, Any]],
    vote_raws: Iterable[dict[str, Any]],
) -> dict[str, Node]:
    """Fractie nodes, keyed by TK ``Id``.

    Several records can share one abbreviation — a party that dissolves and
    reforms gets a fresh record — so they are deduplicated per node key before
    anything is written, with the seated record winning.
    """
    vote_labels = {
        label
        for raw in vote_raws
        if (label := (payload_json(raw).get("ActorFractie") or "").strip())
    }

    newest: dict[str, dict[str, Any]] = {}
    for raw in faction_raws:
        payload = payload_json(raw)
        label = tk_records.faction_label(payload)
        if not label:
            continue
        key = make_node_key(label)
        current = newest.get(key)
        if current is None or tk_records.faction_is_current(
            payload
        ) > tk_records.faction_is_current(current):
            newest[key] = payload

    nodes: dict[str, Node] = {}
    for payload in newest.values():
        parsed = tk_records.faction(
            payload, tk_records.faction_aliases(payload, vote_labels)
        )
        if parsed is None:
            continue
        key, props = parsed
        nodes[props["external_id"]] = Node(
            collection=COLLECTION_FACTIONS,
            type=NodeType.FACTION,
            key=key,
            labels=["TK"],
            props=props,
        )
    _write(store, nodes.values())
    logger.info("Normalized %d factions.", len(nodes))
    return nodes


def link_members_to_committees(
    store: ArangoStore,
    committee_raws: list[dict[str, Any]],
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

    writer = EdgeWriter(store)
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
    store: ArangoStore,
    seat_raws: list[dict[str, Any]],
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
    writer = EdgeWriter(store)
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
    store: ArangoStore,
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


def _write(store: ArangoStore, nodes: Any) -> None:
    with NodeWriter(store) as writer:
        writer.add_all(nodes)
