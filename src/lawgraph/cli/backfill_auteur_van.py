"""Backfill AUTEUR_VAN edges from publications that already have props.actors populated.

The TK dossiers normalize pipeline only creates AUTEUR_VAN edges for documents
processed in the current batch. This script creates them for all existing
publications with actors, making it safe to run repeatedly (edges are idempotent).
"""

from __future__ import annotations

import sys

from dotenv import load_dotenv

from lawgraph.config.settings import (
    COLLECTION_FRACTIES,
    COLLECTION_LEDEN,
    COLLECTION_PUBLICATIONS,
    EDGE_STATUS_CANONIEK,
    RELATION_AUTEUR_VAN,
)
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger, setup_logging
from lawgraph.models import make_node_key

logger = get_logger(__name__)


def backfill_auteur_van(store: ArangoStore) -> int:
    """Create AUTEUR_VAN edges for all publications that have props.actors."""
    aql = f"""
FOR pub IN {COLLECTION_PUBLICATIONS}
  FILTER pub.props.actors != null AND LENGTH(pub.props.actors) > 0
  RETURN {{pub_id: pub._id, actors: pub.props.actors}}
"""
    total = 0
    for row in store.query(aql, {}):
        pub_id: str = row["pub_id"]
        seen_fracties: set[str] = set()

        for actor in row.get("actors") or []:
            rol = actor.get("rol") or ""
            persoon_id = actor.get("persoon_id") or ""
            fractie_naam = (actor.get("fractie") or "").strip()

            if persoon_id:
                lid_key = make_node_key(persoon_id)
                lid_node = store.get_node(COLLECTION_LEDEN, lid_key)
                if lid_node and lid_node.id:
                    try:
                        store.create_edge(
                            from_id=lid_node.id,
                            to_id=pub_id,
                            relation=RELATION_AUTEUR_VAN,
                            source="backfill-auteur-van",
                            status=EDGE_STATUS_CANONIEK,
                            meta={"rol": rol},
                        )
                        total += 1
                    except Exception as exc:
                        logger.debug("Lid→pub edge skipped: %s", exc)

            if fractie_naam and fractie_naam not in seen_fracties:
                seen_fracties.add(fractie_naam)
                fractie_key = make_node_key(fractie_naam)
                fractie_node = store.get_node(COLLECTION_FRACTIES, fractie_key)
                if fractie_node and fractie_node.id:
                    try:
                        store.create_edge(
                            from_id=fractie_node.id,
                            to_id=pub_id,
                            relation=RELATION_AUTEUR_VAN,
                            source="backfill-auteur-van",
                            status=EDGE_STATUS_CANONIEK,
                            meta={"rol": rol},
                        )
                        total += 1
                    except Exception as exc:
                        logger.debug("Fractie→pub edge skipped: %s", exc)

    return total


def main(argv: list[str] | None = None) -> None:
    load_dotenv()
    setup_logging()

    store = ArangoStore()
    n = backfill_auteur_van(store)
    logger.info("backfill-auteur-van: created/updated %d AUTEUR_VAN edges.", n)
    if n == 0:
        logger.warning(
            "No AUTEUR_VAN edges created — check publications have props.actors."
        )
        sys.exit(0)
