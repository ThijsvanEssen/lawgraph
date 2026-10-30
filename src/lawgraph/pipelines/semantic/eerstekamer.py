"""Link Eerste Kamer documents to the Tweede Kamer dossier they belong to.

Both chambers handle the same bill. An EK Kamerstuk carries the number of the TK
kamerstukdossier (``dossier_number``, plus ``dossier_suffix`` for a budget chapter such as
``35925 VII``; a document on more than one bill names the others in ``dossier_numbers``), which
is enough to write the same PART_OF edge the TK documents get, just
cross-chamber. Derived in full on every run: an edge no document supports any more goes.
"""

from __future__ import annotations

from itertools import chain

from lawgraph.config.constants import (
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    RELATION_PART_OF,
    SOURCE_EERSTEKAMER,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, PipelineResult
from lawgraph.db import EdgeWriter
from lawgraph.db.queries.semantic import tk as semantic_tk

from .base import SemanticPipelineBase

logger = get_logger(__name__)

EDGE_SOURCE = "ek-dossier-linker"
# A paper of the Eerste Kamer on the dossier its number names.
DOSSIER_NUMBER_CONFIDENCE = 0.95


class EerstekamerSemanticPipeline(SemanticPipelineBase):
    """Links EK documents to TK kamerstukdossiers via DossierNummer."""

    # The documents linked (their ``source``) and the source of the edges.
    documents_of = SOURCE_EERSTEKAMER
    edge_source = EDGE_SOURCE

    def run(self) -> PipelineResult:
        result = PipelineResult()

        documents = chain(
            semantic_tk.ek_papers_in_tk_dossiers(self.store, self.documents_of),
            semantic_tk.ek_papers_in_other_dossiers(self.store, self.documents_of),
        )
        seen: set[tuple[str, str]] = set()
        edges = EdgeWriter(self.store, what=None, remembers=True)
        for row in self._track(documents, "Eerste Kamer papers"):
            pair = (row["document_key"], row["dossier_key"])
            if pair in seen:
                continue
            seen.add(pair)
            edges.add_doc(
                self._make_edge_doc(
                    from_node=Node.skeleton(COLLECTION_DOCUMENTS, row["document_key"]),
                    to_node=Node.skeleton(COLLECTION_DOSSIERS, row["dossier_key"]),
                    relation=RELATION_PART_OF,
                    source=self.edge_source,
                    confidence=DOSSIER_NUMBER_CONFIDENCE,
                )
            )

        edges.flush_into(result)
        removed = edges.remove_stale_of_source(RELATION_PART_OF, self.edge_source)
        logger.info(
            "%s dossier link: %d edges; %d no paper supports any more removed.",
            self.documents_of,
            edges.written(RELATION_PART_OF),
            removed,
        )
        return result
