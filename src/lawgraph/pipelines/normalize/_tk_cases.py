"""What parliament handles: activities, commitments, documents and their subjects.

An activity, a decision and a document all name the same two things — the
cases on their agenda and the dossiers those cases belong to — so one linker
serves all three; only the relation differs (ABOUT for an activity or
decision, PART_OF for a document).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
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
    RELATION_ACCOMPANIES,
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
from lawgraph.db.queries.normalize import tk as normalize_tk
from lawgraph.pipelines.normalize._tk_deleted import Deleted

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
    nodes = _write_nodes(
        store,
        raw_records,  # walked once: a second walk is a second read of every record
        tk_records.commitment,
        COLLECTION_COMMITMENTS,
        NodeType.COMMITMENT,
    )
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
        if (node_id := node.node_id)
        for case_id in node.props.get("case_ids") or []
    ] + [
        (node_id, COLLECTION_DOSSIERS, make_node_key(str(number)))
        for node in nodes
        if (node_id := node.node_id)
        for number in node.props.get("dossier_numbers") or []
    ]

    writer = EdgeWriter(store, what=f"{relation} edges")
    _queue_existing(store, pairs, relation, writer, source=source)
    writer.flush()
    logger.info("Wrote %d %s edges to cases and dossiers.", writer.added, relation)


def link_decisions_to_activities(
    store: Store, decision_nodes: Iterable[Node], *, source: str
) -> None:
    """MADE_IN from a decision to the activity of its agenda item (``activity_id``), the
    meeting it was taken in, when that activity is stored."""
    pairs = [
        (node_id, COLLECTION_ACTIVITIES, make_node_key(str(activity)))
        for node in decision_nodes
        if (node_id := node.node_id) and (activity := node.props.get("activity_id"))
    ]
    writer = EdgeWriter(store, what="decision to activity edges")
    _queue_existing(store, pairs, RELATION_MADE_IN, writer, source=source)
    writer.flush()
    logger.info("Linked %d decisions to the activity they were taken in.", writer.added)


def link_cases_to_dossiers(
    store: Store,
    *,
    source: str,
    cases: list[str] | None = None,
    dossiers: Sequence[str] = (),
) -> None:
    """PART_OF edges from the stored cases to the dossiers they belong to: every case, or
    on a run over a window the *cases* (``_id``) it touched and the cases that name one of
    the *dossiers* (labels) it wrote, which may be new.

    Cases are normalized by the TK pipeline before any dossier node exists,
    so the link is made here, once the dossiers are in place.
    """
    if cases is None:
        rows: Iterable[dict[str, Any]] = normalize_tk.case_dossier_numbers(store)
    else:
        rows = [
            *normalize_tk.case_dossier_numbers_of(store, cases),
            *(
                normalize_tk.case_dossier_numbers_naming(store, list(dossiers))
                if dossiers
                else ()
            ),
        ]
    pairs = [
        (row["id"], COLLECTION_DOSSIERS, make_node_key(str(number)))
        for row in rows
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
        (node.node_id, COLLECTION_COMMITTEES, make_node_key(committee_id))
        for node in activity_nodes.values()
        if node.node_id and (committee_id := node.props.get("committee_id"))
    ]
    writer = EdgeWriter(store, what="committee edges")
    _queue_existing(store, pairs, RELATION_LED_BY, writer, source=source)
    writer.flush()
    logger.info("Linked %d activities to their lead committee.", writer.added)


def _dossiers_of(activity: Node, activity_by_number: dict[str, Node]) -> list[str]:
    """The dossiers of *activity*, or of the first activity that replaced it
    (``replaced_by``, Activiteit.VervangenDoor) that names any: a moved activity keeps no
    agenda, its commitments are about what the activity that replaced it discussed."""
    seen: set[str] = set()
    queue = [activity]
    while queue:
        current = queue.pop(0)
        numbers = current.props.get("dossier_numbers") or []
        if numbers:
            return list(numbers)
        for number in current.props.get("replaced_by") or []:
            if number not in seen and number in activity_by_number:
                seen.add(number)
                queue.append(activity_by_number[number])
    return []


def link_commitments(
    store: Store,
    commitment_nodes: dict[str, Node],
    activity_nodes: dict[str, Node],
    *,
    source: str,
) -> None:
    """MADE_IN edges to the activity, and ABOUT edges to that activity's dossiers.

    A Toezegging names no dossier of its own; the activity it was made in does, or, when
    that one was moved and kept no agenda, the activity that replaced it
    (``_dossiers_of``).
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
        if activity is None or not node.node_id:
            continue
        writer.add(node.node_id, activity.node_id, RELATION_MADE_IN, source=source)
        dossier_pairs += [
            (node.node_id, COLLECTION_DOSSIERS, make_node_key(str(number)))
            for number in _dossiers_of(activity, activity_by_number)
        ]
    _queue_existing(store, dossier_pairs, RELATION_ABOUT, writer, source=source)
    writer.flush()
    logger.info("Wrote %d commitment edges.", writer.added)


def link_authors(store: Store, document_nodes: dict[str, Node], *, source: str) -> None:
    """AUTHORED edges from every signatory to the document they signed.

    Only people are stored: which faction signed follows from the signatory's
    faction membership at the time.
    """
    documents = [node for node in document_nodes.values() if node.node_id]
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
                node.node_id,
                RELATION_AUTHORED,
                source=source,
                meta={
                    "role": actor.get("role") or "",
                    "function": actor.get("function"),
                    "capacity": actor.get("capacity"),
                },
            )
    writer.flush()
    logger.info("Wrote %d AUTHORED edges.", writer.added)


def link_documents(
    store: Store,
    links: Iterable[tuple[str, dict[str, Any]]],
    *,
    source: str,
) -> None:
    """MADE_IN from a document to the activities it is the record of (a stenogram: its
    debate), and ACCOMPANIES from an attachment to its letter, between nodes that exist.

    *links* are ``(TK id of the document, tk_records.document_links)``. An attachment is
    named by its letter (``attachment_ids``) and names its letter (``attached_to_ids``):
    either one makes the edge, so a run that holds only one of the two papers makes it too.
    """
    links = list(links)
    made_in: list[tuple[str, str]] = []
    accompanies: list[tuple[str, str]] = []
    for document_id, of in links:
        document = make_node_key(document_id)
        made_in += [(document, make_node_key(a)) for a in of.get("activity_ids") or []]
        accompanies += [
            (make_node_key(attachment), document)
            for attachment in of.get("attachment_ids") or []
        ] + [
            (document, make_node_key(letter))
            for letter in of.get("attached_to_ids") or []
        ]
    documents = store.existing_keys(
        COLLECTION_DOCUMENTS,
        {key for pair in accompanies for key in pair} | {d for d, _ in made_in},
    )
    activities = store.existing_keys(COLLECTION_ACTIVITIES, {a for _, a in made_in})

    writer = EdgeWriter(store, what="document links")
    for document, activity in made_in:
        if document in documents and activity in activities:
            writer.add(
                f"{COLLECTION_DOCUMENTS}/{document}",
                f"{COLLECTION_ACTIVITIES}/{activity}",
                RELATION_MADE_IN,
                source=source,
            )
    for attachment, letter in accompanies:
        if attachment != letter and attachment in documents and letter in documents:
            writer.add(
                f"{COLLECTION_DOCUMENTS}/{attachment}",
                f"{COLLECTION_DOCUMENTS}/{letter}",
                RELATION_ACCOMPANIES,
                source=source,
            )
    writer.flush()
    logger.info("Wrote %d document links (MADE_IN, ACCOMPANIES).", writer.added)


# What the edge builders read from a node; the rest of its props (the whole API payload
# among them) is only needed for the write.
LINK_PROPS = (
    "case_ids",
    "dossier_numbers",
    "committee_id",
    "number",
    "activity_number",
    "actors",
    "activity_id",
    "activity_ids",
    "attachment_ids",
    "attached_to_ids",
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
    A record the Kamer deleted (``Verwijderd``, its id and nothing else) is no node: the
    node an earlier run wrote of it is removed, with its edges.
    """
    nodes: dict[str, Node] = {}
    deleted = Deleted(collection)
    with NodeWriter(store) as writer:
        for raw in raw_records:
            payload = payload_json(raw)
            if deleted(payload):
                continue
            parsed = read(payload)
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
    removed = deleted.remove(store)
    if removed:
        logger.info("Removed %d %s the Kamer deleted.", removed, collection)
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
