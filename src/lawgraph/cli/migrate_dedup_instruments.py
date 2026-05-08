"""One-time migration: merge orphan auto-keyed instrument nodes into their
deterministic-keyed counterparts and delete the orphans.

Background
----------
An earlier version of the strafrecht seed pipeline used ``insert_node()``
(ArangoDB auto-assigns a numeric key) rather than ``insert_or_update()`` with
a deterministic key derived from the BWB id.  The BWB normalize pipeline always
uses ``make_node_key(bwb_id)`` as the key, so each Dutch instrument ended up
with two nodes:

  * ``instruments/<number>``   — seed, numeric/auto key, has config_id /
                                  short_title / labels but NO edges
  * ``instruments/bwbr…``      — normalize, deterministic key, has
                                  display_name / citation_title / all edges

This prevented the unique index on ``props.bwb_id`` from being created and
would confuse any code that looks up instruments by bwb_id.

This migration:
1. Finds every numeric-keyed instrument that has a duplicate deterministic-
   keyed sibling (same props.bwb_id).
2. Merges the orphan's props and labels into the deterministic node using
   the new UPSERT-with-MERGE logic (deterministic-key node values win on
   prop conflicts, labels are unioned).
3. Moves any edges from the orphan to the deterministic node (there are none
   currently, but belt-and-suspenders).
4. Deletes the orphan.

Run with:
    python -m lawgraph.cli.migrate_dedup_instruments
"""

from __future__ import annotations

import sys

sys.path.insert(0, "src")

from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger
from lawgraph.models import Node, NodeType, make_node_key

logger = get_logger(__name__)


def _is_numeric_key(key: str) -> bool:
    return key.isdigit()


def _drop_bad_celex_index(store: ArangoStore) -> None:
    """Drop the incorrectly single-field unique index on instrument_articles.props.celex.

    The correct replacement index (celex + article_number composite) will be
    created by _ensure_indexes() at the end of the migration.
    """
    coll = store.db.collection("instrument_articles")
    for idx in coll.indexes():
        if (
            idx.get("type") == "persistent"
            and idx.get("fields") == ["props.celex"]
            and idx.get("unique") is True
        ):
            coll.delete_index(idx["id"])
            logger.info(
                "Dropped bad unique index on instrument_articles['props.celex']"
            )


def run_migration() -> None:
    store = ArangoStore()

    # 0. Drop the incorrectly-specified single-field unique index on
    #    instrument_articles['props.celex'].  Multiple articles from the same
    #    EU directive all share the same CELEX, so a unique index on just that
    #    field is logically wrong.  The correct index is the composite
    #    (celex, article_number) which _ensure_indexes will create afterwards.
    _drop_bad_celex_index(store)

    # 1. Find all numeric-keyed instrument nodes that have a bwb_id OR celex
    orphans = list(
        store.query(
            "FOR doc IN instruments "
            "FILTER doc.props.bwb_id != null OR doc.props.celex != null "
            "RETURN doc"
        )
    )
    orphans = [
        Node.from_document("instruments", doc)
        for doc in orphans
        if _is_numeric_key(str(doc.get("_key", "")))
    ]

    if not orphans:
        logger.info("No orphan auto-keyed instrument nodes found. Nothing to do.")
        return

    logger.info("Found %d orphan auto-keyed instrument nodes.", len(orphans))

    merged = 0
    deleted = 0
    skipped = 0

    for orphan in orphans:
        bwb_id: str | None = orphan.props.get("bwb_id")
        celex: str | None = orphan.props.get("celex")
        if bwb_id:
            det_key = make_node_key(bwb_id)
        elif celex:
            det_key = make_node_key(celex)
        else:
            logger.warning(
                "Orphan %s has neither bwb_id nor celex; skipping.", orphan.key
            )
            skipped += 1
            continue

        if not det_key:
            logger.warning("Orphan %s produced empty det_key; skipping.", orphan.key)
            skipped += 1
            continue
        det_node = store.get_node("instruments", det_key)

        if det_node is None:
            logger.warning(
                "No deterministic node %s found for orphan %s; skipping.",
                det_key,
                orphan.key,
            )
            skipped += 1
            continue

        identifier = bwb_id or celex
        logger.info(
            "Merging instruments/%s → instruments/%s  (%s=%s)",
            orphan.key,
            det_key,
            "bwb_id" if bwb_id else "celex",
            identifier,
        )

        # Build a synthetic node carrying ONLY the orphan's extra data.
        # insert_or_update will MERGE props and UNION labels, so the
        # deterministic node's existing values are preserved.
        extra_node = Node(
            collection="instruments",
            type=NodeType.INSTRUMENT,
            key=det_key,
            labels=list(orphan.labels),
            props=dict(orphan.props),
        )
        store.insert_or_update(extra_node)
        merged += 1

        # 3. Move any edges from orphan to deterministic node.
        #    (Currently none exist, but handle for safety.)
        orphan_id = orphan.id
        det_id = det_node.id
        if orphan_id and det_id:
            # Edges _from orphan
            from_edges = list(
                store.query(
                    "FOR e IN edges FILTER e._from == @id RETURN e",
                    bind_vars={"id": orphan_id},
                )
            )
            for edge in from_edges:
                new_edge = dict(edge)
                new_edge["_from"] = det_id
                # recompute key
                import hashlib

                edge_key = hashlib.sha1(
                    f"{det_id}:{new_edge['relation']}:{new_edge['_to']}".encode()
                ).hexdigest()
                new_edge["_key"] = edge_key
                store.insert_or_update_edge(new_edge)
                store.db.collection("edges").delete(edge["_key"])
                logger.info("  Moved edge _from %s → %s", orphan_id, det_id)

            # Edges _to orphan
            to_edges = list(
                store.query(
                    "FOR e IN edges FILTER e._to == @id RETURN e",
                    bind_vars={"id": orphan_id},
                )
            )
            for edge in to_edges:
                new_edge = dict(edge)
                new_edge["_to"] = det_id
                import hashlib

                edge_key = hashlib.sha1(
                    f"{new_edge['_from']}:{new_edge['relation']}:{det_id}".encode()
                ).hexdigest()
                new_edge["_key"] = edge_key
                store.insert_or_update_edge(new_edge)
                store.db.collection("edges").delete(edge["_key"])
                logger.info("  Moved edge _to %s → %s", orphan_id, det_id)

        # 4. Delete the orphan.
        store.db.collection("instruments").delete(str(orphan.key))
        logger.info("  Deleted orphan instruments/%s", orphan.key)
        deleted += 1

    logger.info(
        "Migration complete: %d merged, %d deleted, %d skipped.",
        merged,
        deleted,
        skipped,
    )

    # Trigger index re-creation now that duplicates are gone.
    logger.info("Re-creating indexes...")
    store._ensure_indexes()
    logger.info("Done.")


if __name__ == "__main__":
    run_migration()
