"""Link Eerste Kamer documents to the Tweede Kamer dossier they belong to.

Both chambers handle the same bill. An EK Kamerstuk carries the number of the TK
kamerstukdossier (``dossier_number``, plus ``dossier_suffix`` for a budget chapter such as
``35925 VII``), which is enough to write the same PART_OF edge the TK documents get, just
cross-chamber.
"""

from __future__ import annotations

from lawgraph.config.constants import (
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    RELATION_PART_OF,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult
from lawgraph.db import EdgeWriter
from lawgraph.db.queries import semantic as semantic_queries

from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "ek-dossier-linker"


class EerstekamerSemanticPipeline(SemanticPipelineBase):
    """Links EK documents to TK kamerstukdossiers via DossierNummer."""

    def run(self) -> PipelineResult:
        result = PipelineResult()

        papers = semantic_queries.ek_papers_in_tk_dossiers(self.store)
        rows = list(self._track(papers, "Eerste Kamer papers"))
        if not rows:
            logger.info("EK dossier link: no EK stuk matches a TK dossier.")
            return result

        seen: set[tuple[str, str]] = set()
        edges = EdgeWriter(self.store, what=None)
        for row in rows:
            pair = (row["document_key"], row["dossier_key"])
            if pair in seen:
                continue
            seen.add(pair)
            edges.add_doc(
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
                        "dossier_suffix": row.get("dossier_suffix"),
                        "chamber": "EK",
                    },
                )
            )

        edges.flush_into(result)
        return result
