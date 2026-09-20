"""Link Eerste Kamer documents to the Tweede Kamer dossier they belong to.

Both chambers handle the same bill. An EK Kamerstuk carries a
``DossierNummer`` that is the TK kamerstukdossier number, which is enough to
write the same PART_OF edge the TK documents get — just cross-chamber.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    RELATION_PART_OF,
    SOURCE_EERSTEKAMER,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult
from lawgraph.core.time import iso_timestamp

from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "ek-dossier-linker"


class EerstekamerDossierLinkSemanticPipeline(SemanticPipelineBase):
    """Links EK documents to TK kamerstukdossiers via DossierNummer."""

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        result = PipelineResult()

        since_filter = (
            "FILTER document.props.fetched_at >= @since" if since is not None else ""
        )
        aql = f"""
FOR document IN {COLLECTION_DOCUMENTS}
  FILTER document.props.source == @source
  FILTER document.props.dossier_number != null
  {since_filter}
  LET dossier = FIRST(
    FOR d IN {COLLECTION_DOSSIERS}
      FILTER d.props.number == TO_STRING(document.props.dossier_number)
      LIMIT 1
      RETURN d
  )
  FILTER dossier != null
  LIMIT 10000
  RETURN {{
    document_key: document._key,
    dossier_key: dossier._key,
    dossier_number: document.props.dossier_number
  }}
"""
        bind_vars: dict[str, Any] = {"source": SOURCE_EERSTEKAMER}
        if since is not None:
            bind_vars["since"] = iso_timestamp(since)
        rows = list(self.store.query(aql, bind_vars))
        if not rows:
            logger.info("EK dossier link: no EK stuk matches a TK dossier.")
            return result

        seen: set[tuple[str, str]] = set()
        edge_batch: list[dict[str, Any]] = []
        for row in rows:
            pair = (row["document_key"], row["dossier_key"])
            if pair in seen:
                continue
            seen.add(pair)
            self._queue_edge(
                edge_batch,
                self._make_edge_doc(
                    from_node=Node(
                        collection=COLLECTION_DOCUMENTS,
                        type=NodeType.DOCUMENT,
                        key=row["document_key"],
                        props={},
                    ),
                    to_node=Node(
                        collection=COLLECTION_DOSSIERS,
                        type=NodeType.DOSSIER,
                        key=row["dossier_key"],
                        props={},
                    ),
                    relation=RELATION_PART_OF,
                    source=SEMANTIC_SOURCE,
                    confidence=0.95,
                    meta={
                        "dossier_number": str(row["dossier_number"]),
                        "chamber": "EK",
                    },
                ),
                result,
            )

        self._write_batch(edge_batch, result)
        logger.info("EK dossier link: %s.", result.summary())
        return result
