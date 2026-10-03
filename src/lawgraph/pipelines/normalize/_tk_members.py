"""People in parliament: committees, members, factions and their memberships.

Every function here takes the raw TK records for one entity and returns the
nodes it wrote, keyed by the TK identifier the other builders join on. Reads
and writes are bulk: one existence lookup per collection, one edge flush.
A record the Kamer deleted (``Verwijderd``, its id and nothing else) is no node or
edge, and what an earlier run wrote of it is removed.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_COMMITTEES,
    COLLECTION_EDGES,
    COLLECTION_FACTIONS,
    COLLECTION_MEMBERS,
    RELATION_MEMBER_OF,
)
from lawgraph.core import seat_periods, tk_records
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, make_node_key
from lawgraph.core.raw_records import payload_json
from lawgraph.db import EdgeWriter, NodeWriter, Store, make_edge_doc
from lawgraph.pipelines.normalize._tk_deleted import Deleted

logger = get_logger(__name__)

# The FractieZetelPersoon id a seat period carries until it is written (not stored).
_RECORD_ID = "_record_id"


def normalize_committees(
    store: Store, raw_records: Iterable[dict[str, Any]]
) -> dict[str, Node]:
    """Commissie nodes, keyed by TK ``Id``; the node of a committee the Kamer deleted is
    removed."""
    nodes: dict[str, Node] = {}
    deleted = Deleted(COLLECTION_COMMITTEES)
    for raw in raw_records:
        payload = payload_json(raw)
        if deleted(payload):
            continue
        parsed = tk_records.committee(payload)
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
    tk_records.unique_committee_slugs([node.props for node in nodes.values()])
    _write(store, nodes.values())
    removed = deleted.remove(store)
    logger.info(
        "Normalized %d committees; removed %d the Kamer deleted.", len(nodes), removed
    )
    return nodes


def normalize_members(
    store: Store, raw_records: Iterable[dict[str, Any]]
) -> dict[str, Node]:
    """Persoon nodes, keyed by TK ``Id``; the node of a person the Kamer deleted is removed."""
    nodes: dict[str, Node] = {}
    deleted = Deleted(COLLECTION_MEMBERS)
    for raw in raw_records:
        payload = payload_json(raw)
        if deleted(payload):
            continue
        parsed = tk_records.member(payload)
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
    removed = deleted.remove(store)
    logger.info(
        "Normalized %d members; removed %d the Kamer deleted.", len(nodes), removed
    )
    return nodes


def normalize_factions(
    store: Store,
    faction_raws: Iterable[dict[str, Any]],
    vote_labels: set[str],
    seat_raws: Iterable[dict[str, Any]],
) -> dict[str, Node]:
    """Faction nodes, by the TK ``Id`` of every Fractie record.

    Several records can share one abbreviation: a faction that returns gets a fresh record
    (50PLUS 2012-2021 and from 2025, Krol, Van Kooten-Arissen), and the Kamer names either
    one on votes and seats, the old one also on a vote of today. They are one faction: one
    node, whose props come from the seated (else the latest changed) record and whose
    period spans them all, reached by the id of each of them. *vote_labels* are the
    spellings votes use for a faction (``Stemming.ActorFractie``). A deleted record is none of
    them; a faction whose every record is deleted is removed. *seat_raws* are every
    FractieZetelPersoon record: the seats date the faction (``seat_periods.seated_bounds``).
    """
    by_key: dict[str, list[dict[str, Any]]] = {}
    deleted = Deleted(COLLECTION_FACTIONS, key=None)  # keyed by the abbreviation
    for raw in faction_raws:
        payload = payload_json(raw)
        if deleted(payload):
            continue
        label = tk_records.faction_label(payload)
        if label:
            by_key.setdefault(make_node_key(label), []).append(payload)

    seats: dict[str, list[seat_periods.Period]] = {}
    for raw in seat_raws:
        held = tk_records.seat_holding(payload_json(raw))
        if held:
            seats.setdefault(held[1], []).append(held[2])

    nodes: dict[str, Node] = {}
    for records in by_key.values():
        current = max(records, key=tk_records.faction_is_current)
        parsed = tk_records.faction(
            current, tk_records.faction_aliases(current, vote_labels), records
        )
        if parsed is None:
            continue
        key, props = parsed
        props["active_from"], props["active_until"] = seat_periods.seated_bounds(
            props["active_from"],
            props["active_until"],
            [p for fid in props["external_ids"] for p in seats.get(fid, [])],
        )
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
    removed = deleted.remove(store)
    logger.info(
        "Normalized %d factions (%d Fractie records); removed %d the Kamer deleted.",
        len(written),
        len(nodes),
        removed,
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


def _recency(period: dict[str, Any], record_id: str) -> tuple[str, bool, str, str]:
    """How late a seat period is: by its start, then an open end after a closed one, then
    its end, then the record id. The one edge of a member and a faction carries the latest,
    whatever order the records were read in."""
    end = period.get("to_date")
    return (period.get("from_date") or "", end is None, end or "", record_id)


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
    and rejoined a party has one edge carrying the latest period and the ids of every
    FractieZetelPersoon it is made of; the full timeline is denormalised onto the member
    as ``faction_memberships`` so a profile renders without a traversal. The periods are
    read so they hold together (``seat_periods``: an end before the start, two
    fractievoorzitters at once). The edge of a seat the Kamer deleted goes.
    """
    seats: dict[str, dict[str, Any]] = {}  # edge key -> the edge
    ranks: dict[
        str, tuple[str, bool, str, str]
    ] = {}  # edge key -> _recency of its period
    timeline: dict[str, list[dict[str, Any]]] = {}
    changed: dict[str, str] = {}  # faction key -> the day one of its seats last changed
    deleted = Deleted(COLLECTION_EDGES)

    holdings: list[seat_periods.Holding] = []
    for raw in seat_raws:
        payload = payload_json(raw)
        parsed = None if deleted(payload) else tk_records.seat_holding(payload)
        if parsed is None:
            continue
        person_id, faction_id, period = parsed
        faction_node = faction_nodes.get(faction_id)
        if not (person_id in member_nodes and faction_node):
            continue
        day = tk_records.seat_changed_on(payload)
        if day and faction_node.key and day > changed.get(faction_node.key, ""):
            changed[faction_node.key] = day
        # The record id rides along through seat_periods, which copies a period's keys.
        holdings.append(
            (
                person_id,
                faction_id,
                {**period, _RECORD_ID: str(payload.get("Id") or "")},
            )
        )

    mended = seat_periods.mend_reversed_ends(holdings)
    held = seat_periods.split_overlapping_chairs(mended)
    for person_id, faction_id, period in held:
        period = dict(period)
        record_id = period.pop(_RECORD_ID, "")
        member_node, faction_node = member_nodes[person_id], faction_nodes[faction_id]
        edge = make_edge_doc(
            member_node.node_id or "",
            faction_node.node_id or "",
            RELATION_MEMBER_OF,
            source=source,
            meta=period,
        )
        key = edge["_key"]
        kept = seats.get(key)
        ids = sorted({*(kept["meta"]["record_ids"] if kept else []), record_id} - {""})
        rank = _recency(period, record_id)
        if kept is None or rank > ranks[key]:
            seats[key], ranks[key] = edge, rank
        seats[key]["meta"]["record_ids"] = ids
        timeline.setdefault(person_id, []).append(
            {
                "faction_id": faction_node.node_id,
                "faction_key": faction_node.key,
                "name": faction_node.props.get("name"),
                "abbreviation": faction_node.props.get("abbreviation"),
                "aliases": faction_node.props.get("aliases") or [],
                **period,
            }
        )

    writer = EdgeWriter(store, what="faction seat edges")
    for edge in seats.values():
        writer.add_doc(edge)
    writer.flush()
    removed = deleted.remove(store)
    _write_timelines(store, member_nodes, timeline)
    _write_seat_changes(store, faction_nodes, changed)
    logger.info(
        "Linked %d members to factions (%d with a timeline); removed %d seats the "
        "Kamer deleted; left out %d whose end lies before its start and no later seat.",
        writer.added,
        len(timeline),
        removed,
        len(holdings) - len(mended),
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


def _write_seat_changes(
    store: Store, faction_nodes: dict[str, Node], changed: dict[str, str]
) -> None:
    """``seats_changed_on`` on each faction: the day one of its seats last changed
    (``lawgraph check`` holds the date of the curated seating plan against it)."""
    updated = []
    for node in {n.key: n for n in faction_nodes.values()}.values():
        day = changed.get(node.key or "")
        if day and node.props.get("seats_changed_on") != day:
            node.props["seats_changed_on"] = day
            updated.append(node.to_document())
    if updated:
        store.bulk_insert_or_update_nodes(COLLECTION_FACTIONS, updated)


def _write(store: Store, nodes: Any) -> None:
    with NodeWriter(store) as writer:
        writer.add_all(nodes)


def name_nameless_members(
    store: Store,
    member_nodes: dict[str, Node],
    votes_by_decision: dict[str, list[tk_records.VoteCast]],
    document_nodes: dict[str, Node],
) -> None:
    """Give a member the Kamer gives no name (an empty Persoon record) the name the records
    that name its Persoon_Id carry: its roll-call votes ("Nobel, J.N.J." is J.N.J. Nobel) and
    the papers it signed (``DocumentActor``: "B.J. Bruins"), the one they carry most."""
    nameless = {
        person_id
        for person_id, node in member_nodes.items()
        if not node.props.get("name")
    }
    names: dict[str, Counter[str]] = {}
    for votes in votes_by_decision.values():
        for cast in votes:
            if cast.person_id in nameless and cast.actor_name:
                names.setdefault(cast.person_id, Counter())[cast.actor_name] += 1
    for document in document_nodes.values():
        for actor in document.props.get("actors") or []:
            person_id = actor.get("person_id")
            if person_id in nameless and actor.get("name"):
                names.setdefault(person_id, Counter())[actor["name"]] += 1
    updated = []
    for person_id, counted in names.items():
        name = tk_records.display_person_name(counted.most_common(1)[0][0])
        if not name:
            continue
        node = member_nodes[person_id]
        node.props["name"] = node.props["display_name"] = name
        updated.append(node.to_document())
    if updated:
        store.bulk_insert_or_update_nodes(COLLECTION_MEMBERS, updated)
    logger.info(
        "Named %d members the Kamer gives no name by their votes and signatures.",
        len(updated),
    )
