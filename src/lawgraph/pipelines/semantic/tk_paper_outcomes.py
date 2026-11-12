"""``lawgraph semantic tk-paper-outcomes``: how each motion and amendment ended.

Per document the decisions of the Kamer on it (``queries/decisions.motion_documents``: the oldest
document of the case a decision singled out, or the Kamerstuk a vote of the Eerste Kamer on a
motion is about) give ``outcome`` (``aangenomen``, ``verworpen``, ``ingetrokken``,
``aangehouden``, ``vervallen``; without a decision the status the page of a motion of the
Eerste Kamer states, else ``vervangen`` for a document a newer one replaces), ``decided_on``,
``tally`` (the seats per choice) and ``decision`` (the key of the decision):
``core/votes.py``. A decision comes days after its document and can change it again
(held, then voted), so every run reads every decision on a motion or an amendment (some
60,000) and writes only the documents whose outcome changed, compared with what
``lg_document_light`` keeps of them; a document that lost its outcome gets nulls. The trigger on
``documents`` keeps the light row with it, which the lists of documents read.

With ``--touched-since`` it reads only the papers a poll touched since then
(``semantic/_touched.py``, ``touched_papers``) and comes to the same for them as a run over
all. It removes nothing, so the nightly run over all is only needed for what is touched in
another way (the status on the page of a motion of the Eerste Kamer, a replacement that went).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from lawgraph.config.constants import COLLECTION_DOCUMENTS
from lawgraph.core.batching import chunked
from lawgraph.core.logging import get_logger
from lawgraph.core.models import NodeType, PipelineResult, key_of
from lawgraph.core.votes import document_outcome
from lawgraph.db.queries import document_outcomes as queries

from . import _touched as touched
from .base import SemanticPipelineBase

logger = get_logger(__name__)

# Documents written in one statement.
_BATCH = 1_000


class TKPaperOutcomesSemanticPipeline(SemanticPipelineBase):
    """Write ``outcome``, ``decided_on``, ``tally`` and ``decision`` on every motion and
    amendment whose outcome changed."""

    def run(self, *, touched_since: dt.datetime | None = None) -> PipelineResult:
        result = PipelineResult()
        papers = (
            None
            if touched_since is None
            else touched.touched_papers(self.store, touched_since)
        )
        decisions = queries.document_decisions(self.store, papers)
        replaced = queries.replaced_documents(self.store, papers)
        stated = queries.stated_statuses(self.store, papers)
        kept = queries.kept_outcomes(self.store, papers)
        changed: list[dict[str, Any]] = []
        documents = sorted(set(decisions) | replaced | set(stated) | set(kept))
        for document in self._track(documents, "papers", total=len(documents)):
            props = document_outcome(
                decisions.get(document, []), document in replaced, stated.get(document)
            )
            if props != kept.get(document, dict.fromkeys(props)):
                changed.append(
                    {
                        "key": key_of(document),
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
