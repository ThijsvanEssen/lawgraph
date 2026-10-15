"""Semantic pipeline: ``SAME_AS`` from a document of the Staatsblad or the Staatscourant to the
publication of the BWB of the same official id (``stb-2019-33``, ``stcrt-2020-12345``).

The one publication is in the graph twice: as the document its own source gives (its text, a nota
van toelichting or a ministerial regulation: ``documents/stb_stb_2019_33``) and as the BWB
names it in the versions of the articles it introduced, amended or repealed
(``instruments/stb_2019_33``, ``semantic bwb-amendments``). The key of the document is that of
the publication after its source's prefix, so the edge is derived from the keys alone, exact.
Every run derives them in full and removes those no longer derived. After ``bwb-amendments``
and the normalize of the Staatsblad and the Staatscourant.
"""

from __future__ import annotations

from lawgraph.config.constants import (
    RELATION_SAME_AS,
    SOURCE_STAATSBLAD,
    SOURCE_STAATSCOURANT,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.core.provenance import BASIS_OFFICIAL_ID
from lawgraph.db import EdgeWriter
from lawgraph.db.queries.semantic import bwb as semantic_bwb

from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "bwb-publication-linker"

# The documents of each source, by the prefix of their keys (``make_node_key(prefix, id)``).
DOCUMENTS = ((SOURCE_STAATSBLAD, "stb_"), (SOURCE_STAATSCOURANT, "stcrt_"))


class BWBPublicationsSemanticPipeline(SemanticPipelineBase):
    """``SAME_AS`` from each document of the Staatsblad and the Staatscourant to the publication
    of the BWB of its official id."""

    def run(self) -> PipelineResult:
        result = PipelineResult()
        edges = EdgeWriter(self.store, what=None, remembers=True)
        for source, prefix in DOCUMENTS:
            pairs = semantic_bwb.same_publications(self.store, source, prefix)
            for pair in self._track(pairs, f"papers of {source}", total=len(pairs)):
                edges.add(
                    pair["doc_id"],
                    pair["inst_id"],
                    RELATION_SAME_AS,
                    source=SEMANTIC_SOURCE,
                    confidence=1.0,
                    meta={"basis": BASIS_OFFICIAL_ID},
                )
            logger.info(
                "%s: %d papers SAME_AS the BWB publication of their id.",
                source,
                len(pairs),
            )
        edges.flush_into(result)
        removed = edges.remove_stale_of_source(RELATION_SAME_AS, SEMANTIC_SOURCE)
        logger.info("Removed %d SAME_AS no longer derived.", removed)
        return result
