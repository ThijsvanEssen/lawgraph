"""Semantic pipeline: EK stukken → DEEL_VAN_DOSSIER → TK kamerstukdossier.

The Eerste Kamer processes the same legislative bills as the Tweede Kamer.
Each EK Kamerstuk carries a ``DossierNummer`` that corresponds directly to
the TK kamerstukdossier ``nummer`` field.

This pipeline creates DEEL_VAN_DOSSIER edges from EK publications to the
matching TK kamerstukdossier.  It mirrors what the TK normalize pipeline
does for TK documents — just cross-chamber.
"""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    COLLECTION_KAMERSTUKDOSSIERS,
    COLLECTION_PUBLICATIONS,
    RELATION_DEEL_VAN_DOSSIER,
    SOURCE_EERSTEKAMER,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult

from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "ek-dossier-linker"


class EerstekamerDossierLinkPipeline(SemanticPipelineBase):
    """Links EK publications to TK kamerstukdossiers via DossierNummer."""

    def run(self, *, since: Any = None) -> PipelineResult:
        result = PipelineResult()

        # EK stukken that have a dossier_nummer
        since_filter = "FILTER pub.props.fetched_at >= @since" if since else ""
        aql = f"""
FOR pub IN publications
  FILTER pub.props.source == @source
  FILTER pub.props.dossier_nummer != null
  {since_filter}
  LET dos = FIRST(
    FOR d IN kamerstukdossiers
      FILTER TO_STRING(d.props.nummer) == TO_STRING(pub.props.dossier_nummer)
        OR d.props.kamerstuknummer == TO_STRING(pub.props.dossier_nummer)
      LIMIT 1
      RETURN d
  )
  FILTER dos != null
  LIMIT 10000
  RETURN {{
    pub_id: pub._id, pub_key: pub._key,
    dos_id: dos._id, dos_key: dos._key,
    dossier_nummer: pub.props.dossier_nummer
  }}
"""
        bind_vars: dict[str, Any] = {"source": SOURCE_EERSTEKAMER}
        if since:
            bind_vars["since"] = (
                since.isoformat() if hasattr(since, "isoformat") else str(since)
            )
        try:
            rows = list(self.store.query(aql, bind_vars))
        except Exception as exc:
            logger.warning("EK dossier link query failed: %s", exc)
            return result

        if not rows:
            logger.debug(
                "EK dossier link: no EK stukken with matching TK dossiers found."
            )
            return result

        logger.info(
            "EK dossier link: processing %d EK-publication / TK-dossier pairs.",
            len(rows),
        )

        seen: set[tuple[str, str]] = set()
        for row in rows:
            pub_id = row.get("pub_id")
            pub_key = row.get("pub_key")
            dos_id = row.get("dos_id")
            dos_key = row.get("dos_key")
            dossier_nummer = row.get("dossier_nummer")

            if not pub_id or not dos_id:
                result.skipped += 1
                continue

            pair = (pub_id, dos_id)
            if pair in seen:
                continue
            seen.add(pair)

            pub_node = Node(
                collection=COLLECTION_PUBLICATIONS,
                type=NodeType.PUBLICATION,
                key=pub_key,
                props={},
            )
            dos_node = Node(
                collection=COLLECTION_KAMERSTUKDOSSIERS,
                type=NodeType.DOSSIER,
                key=dos_key,
                props={},
            )

            created = self._create_semantic_edge(
                from_node=pub_node,
                to_node=dos_node,
                relation=RELATION_DEEL_VAN_DOSSIER,
                source=SEMANTIC_SOURCE,
                confidence=0.95,
                meta={"dossier_nummer": str(dossier_nummer), "chamber": "EK"},
                result=result,
            )
            if created:
                result.created += 1
            else:
                result.updated += 1

        logger.info("EK dossier link: %s.", result.summary())
        return result
