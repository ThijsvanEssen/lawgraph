"""What parliament handles: activities, commitments, documents and their subjects.

An activity, a decision and a document all name the same two things — the
cases on their agenda and the dossiers those cases belong to — so one linker
serves all three; only the relation differs (ABOUT for an activity or
decision, PART_OF for a document).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ACTIVITIES,
    COLLECTION_CASES,
    COLLECTION_COMMITMENTS,
    COLLECTION_COMMITTEES,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_MEMBERS,
    RELATION_ABOUT,
    RELATION_AUTHORED,
    RELATION_LED_BY,
    RELATION_MADE_IN,
    RELATION_PART_OF,
)
from lawgraph.core import tk_records
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, make_node_key
from lawgraph.core.raw_records import payload_json
from lawgraph.db import EdgeWriter, NodeWriter, Store
from lawgraph.db.queries import normalize as normalize_queries

logger = get_logger(__name__)


def normalize_activities(
    store: Store, raw_records: Iterable[dict[str, Any]]
) -> dict[str, Node]:
    """Activiteit nodes, keyed by TK ``Id``."""
    nodes = _write_nodes(
        store,
        raw_records,
        tk_records.activity,
        COLLECTION_ACTIVITIES,
        NodeType.ACTIVITY,
    )
    logger.info("Normalized %d activities.", len(nodes))
    return nodes


def normalize_commitments(
    store: Store, raw_records: Iterable[dict[str, Any]]
) -> dict[str, Node]:
    """Toezegging nodes, keyed by TK ``Id``."""
    unknown: set[str] = set()

    def read(payload: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
        unknown.update(tk_records.unknown_commitment_statuses([payload]))
        return tk_records.commitment(payload)

    nodes = _write_nodes(
        store,
        raw_records,  # walked once: a second walk is a second read of every record
        read,
        COLLECTION_COMMITMENTS,
        NodeType.COMMITMENT,
    )
    if unknown:
        logger.warning("Toezegging statuses not in the status map: %s", sorted(unknown))
    logger.info("Normalized %d commitments.", len(nodes))
    return nodes


def normalize_documents(
    store: Store, raw_records: Iterable[dict[str, Any]]
) -> dict[str, Node]:
    """Document (Kamerstuk) nodes, keyed by TK ``Id``."""
    nodes = _write_nodes(
        store,
        raw_records,
        tk_records.document,
        COLLECTION_DOCUMENTS,
        NodeType.DOCUMENT,
        labels=["TK", "Kamerstuk"],
    )
    logger.info("Normalized %d documents.", len(nodes))
    return nodes


def link_subjects(
    store: Store,
    nodes: Iterable[Node],
    relation: str,
    *,
    source: str,
) -> None:
    """*relation* edges from each node to the cases and dossiers it names.

    Both endpoints are resolved with one existence lookup per collection, so
    the cost does not grow with the number of nodes.
    """
    nodes = list(nodes)
    pairs: list[tuple[str, str, str]] = [
        (node_id, COLLECTION_CASES, make_node_key(case_id))
        for node in nodes
        if (node_id := node.arango_id)
        for case_id in node.props.get("case_ids") or []
    ] + [
        (node_id, COLLECTION_DOSSIERS, make_node_key(str(number)))
        for node in nodes
        if (node_id := node.arango_id)
        for number in node.props.get("dossier_numbers") or []
    ]

    writer = EdgeWriter(store, what=f"{relation} edges")
    _queue_existing(store, pairs, relation, writer, source=source)
    writer.flush()
    logger.info("Wrote %d %s edges to cases and dossiers.", writer.added, relation)


def link_cases_to_dossiers(store: Store, *, source: str) -> None:
    """PART_OF edges from every stored case to the dossiers it belongs to.

    Cases are normalized by the TK pipeline before any dossier node exists,
    so the link is made here, once the dossiers are in place.
    """
    pairs = [
        (row["id"], COLLECTION_DOSSIERS, make_node_key(str(number)))
        for row in normalize_queries.case_dossier_numbers(store)
        for number in row["dossier_numbers"] or []
    ]
    writer = EdgeWriter(store, what="case to dossier edges")
    _queue_existing(store, pairs, RELATION_PART_OF, writer, source=source)
    writer.flush()
    logger.info("Linked %d cases to dossiers.", writer.added)


def link_activities_to_committees(
    store: Store, activity_nodes: dict[str, Node], *, source: str
) -> None:
    """LED_BY edges from an activity to its voortouwcommissie (absent: plenary)."""
    pairs = [
        (node.arango_id, COLLECTION_COMMITTEES, make_node_key(committee_id))
        for node in activity_nodes.values()
        if node.arango_id and (committee_id := node.props.get("committee_id"))
    ]
    writer = EdgeWriter(store, what="committee edges")
    _queue_existing(store, pairs, RELATION_LED_BY, writer, source=source)
    writer.flush()
    logger.info("Linked %d activities to their lead committee.", writer.added)


def link_commitments(
    store: Store,
    commitment_nodes: dict[str, Node],
    activity_nodes: dict[str, Node],
    *,
    source: str,
) -> None:
    """MADE_IN edges to the activity, and ABOUT edges to that activity's dossiers.

    A Toezegging names no dossier of its own; the activity it was made in does.
    """
    activity_by_number = {
        number: node
        for node in activity_nodes.values()
        if (number := node.props.get("number"))
    }

    writer = EdgeWriter(store, what="commitment edges")
    dossier_pairs: list[tuple[str, str, str]] = []
    for node in commitment_nodes.values():
        activity = activity_by_number.get(node.props.get("activity_number"))
        if activity is None or not node.arango_id:
            continue
        writer.add(node.arango_id, activity.arango_id, RELATION_MADE_IN, source=source)
        dossier_pairs += [
            (node.arango_id, COLLECTION_DOSSIERS, make_node_key(str(number)))
            for number in activity.props.get("dossier_numbers") or []
        ]
    _queue_existing(store, dossier_pairs, RELATION_ABOUT, writer, source=source)
    writer.flush()
    logger.info("Wrote %d commitment edges.", writer.added)


def link_authors(store: Store, document_nodes: dict[str, Node], *, source: str) -> None:
    """AUTHORED edges from every signatory to the document they signed.

    Only people are stored: which faction signed follows from the signatory's
    faction membership at the time.
    """
    documents = [node for node in document_nodes.values() if node.arango_id]
    known_members = store.existing_keys(
        COLLECTION_MEMBERS,
        {
            make_node_key(str(actor["person_id"]))
            for node in documents
            for actor in node.props.get("actors") or []
            if actor.get("person_id")
        },
    )

    writer = EdgeWriter(store, what="AUTHORED edges")
    for node in documents:
        for actor in node.props.get("actors") or []:
            person_id = actor.get("person_id")
            if not person_id:
                continue
            member_key = make_node_key(str(person_id))
            if member_key not in known_members:
                continue
            writer.add(
                f"{COLLECTION_MEMBERS}/{member_key}",
                node.arango_id,
                RELATION_AUTHORED,
                source=source,
                meta={"role": actor.get("role") or ""},
            )
    writer.flush()
    logger.info("Wrote %d AUTHORED edges.", writer.added)


# What the edge builders read from a node; the rest of its props (the whole API payload
# among them) is only needed for the write.
LINK_PROPS = (
    "case_ids",
    "dossier_numbers",
    "committee_id",
    "number",
    "activity_number",
    "actors",
    "case_kinds_by_dossier",
    "vote_kind",
)


def link_node(node: Node) -> Node:
    """*node* with only the props the edge builders read: what is kept after the write."""
    return Node(
        collection=node.collection,
        type=node.type,
        key=node.key,
        props={name: node.props[name] for name in LINK_PROPS if name in node.props},
        _skip_validation=True,
    )


def _write_nodes(
    store: Store,
    raw_records: Iterable[dict[str, Any]],
    read: Any,
    collection: str,
    node_type: NodeType,
    *,
    labels: list[str] | None = None,
) -> dict[str, Node]:
    """Write the node of every raw record as it is read; keep a ``link_node`` per TK ``Id``.

    With 130K documents the full nodes are over a gigabyte; the edges need a few props.
    """
    nodes: dict[str, Node] = {}
    with NodeWriter(store) as writer:
        for raw in raw_records:
            parsed = read(payload_json(raw))
            if parsed is None:
                continue
            key, props = parsed
            node = Node(
                collection=collection,
                type=node_type,
                key=key,
                labels=labels or ["TK"],
                props=props,
            )
            writer.add(node)
            nodes[props["external_id"]] = link_node(node)
    return nodes


def _queue_existing(
    store: Store,
    pairs: list[tuple[str, str, str]],
    relation: str,
    writer: EdgeWriter,
    *,
    source: str,
) -> None:
    """Queue ``from_id -> collection/key`` edges for the keys that exist."""
    for collection in {collection for _, collection, _ in pairs}:
        keys = {key for _, coll, key in pairs if coll == collection}
        existing = store.existing_keys(collection, keys)
        for from_id, coll, key in pairs:
            if coll == collection and key in existing:
                writer.add(from_id, f"{collection}/{key}", relation, source=source)
