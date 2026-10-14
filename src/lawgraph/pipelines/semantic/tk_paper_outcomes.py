"""``lawgraph semantic tk-paper-outcomes``: how each motion and amendment ended.

Per paper the decisions of the Kamer on it (``queries/decisions.motion_papers``: the oldest
paper of the case a decision singled out, or the Kamerstuk a vote of the Eerste Kamer on a
motion is about) give ``outcome`` (``aangenomen``, ``verworpen``, ``ingetrokken``,
``aangehouden``, ``vervallen``; without a decision the status the page of a motion of the
Eerste Kamer states, else ``vervangen`` for a paper a newer one replaces), ``decided_on``,
``tally`` (the seats per choice) and ``decision`` (the key of the decision):
``core/votes.py``. A decision comes days after its paper and can change it again
(held, then voted), so every run reads every decision on a motion or an amendment (some
60,000) and writes only the papers whose outcome changed, compared with what
``lg_document_light`` keeps of them; a paper that lost its outcome gets nulls. The trigger on
``documents`` keeps the light row with it, which the lists of papers read.
"""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import COLLECTION_DOCUMENTS
from lawgraph.core.batching import chunked
from lawgraph.core.logging import get_logger
from lawgraph.core.models import NodeType, PipelineResult, key_of
from lawgraph.core.votes import paper_outcome
from lawgraph.db.queries import paper_outcomes as queries

from .base import SemanticPipelineBase

logger = get_logger(__name__)

# Papers written in one statement.
_BATCH = 1_000


class TKPaperOutcomesSemanticPipeline(SemanticPipelineBase):
    """Write ``outcome``, ``decided_on``, ``tally`` and ``decision`` on every motion and
    amendment whose outcome changed."""

    def run(self) -> PipelineResult:
        result = PipelineResult()
        decisions = queries.paper_decisions(self.store)
        replaced = queries.replaced_papers(self.store)
        stated = queries.stated_statuses(self.store)
        kept = queries.kept_outcomes(self.store)
        changed: list[dict[str, Any]] = []
        papers = sorted(set(decisions) | replaced | set(stated) | set(kept))
        for paper in self._track(papers, "papers", total=len(papers)):
            props = paper_outcome(
                decisions.get(paper, []), paper in replaced, stated.get(paper)
            )
            if props != kept.get(paper, dict.fromkeys(props)):
                changed.append(
                    {
                        "_key": key_of(paper),
                        "type": NodeType.DOCUMENT.value,
                        "labels": [],
                        "props": props,
                    }
                )
            else:
                result.unchanged += 1
        for batch in chunked(changed, _BATCH):
            self.store.bulk_insert_or_update_nodes(COLLECTION_DOCUMENTS, batch)
        result.updated = len(changed)
        logger.info(
            "Outcomes of %d papers (%d with a decision, %d replaced): %d changed.",
            result.updated + result.unchanged,
            len(decisions),
            len(replaced),
            result.updated,
        )
        return result
