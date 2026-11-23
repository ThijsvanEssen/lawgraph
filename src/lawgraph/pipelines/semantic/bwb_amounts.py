"""``semantic bwb-amounts``: the numbers in the text of every version of every article.

Of each regulation the ArticleVersions are read (their text, parts, tables and redactions,
as ``normalize bwb`` wrote them; no XML) and their amounts, percentages, time limits and
dates (``core.bwb_amounts``) kept in ``lg_amounts``, a row each. A new toestand that changes
an amount is a new version with a row of its own; the old one keeps its row and holds until
the new one begins. Only a row that changed is written.

``--since``: the regulations whose toestand was fetched since then (the daily run, after
``normalize bwb``). Without it every one, in slices if need be: ``--after BWB-ID`` starts
past that regulation, ``--limit N`` stops after N, and the log names the last one read.
"""

from __future__ import annotations

import datetime as dt

from lawgraph.core.bwb_amounts import amounts
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.core.time import iso_timestamp
from lawgraph.db.queries import amounts as amount_queries
from lawgraph.db.queries.semantic import bwb as semantic_bwb
from lawgraph.db.store import GraphStore

from .base import SemanticPipelineBase

logger = get_logger(__name__)

# Regulations read at a time.
_BATCH = 100


class BWBAmountsSemanticPipeline(SemanticPipelineBase):
    """The numbers of every version of the regulations read, into ``lg_amounts``."""

    def __init__(
        self, *, store: GraphStore, after: str | None = None, limit: int | None = None
    ) -> None:
        super().__init__(store=store)
        self.after = after
        self.limit = limit

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        result = PipelineResult()
        regulations = semantic_bwb.regulations_of_toestanden(
            self.store,
            since_iso=iso_timestamp(since),
            after=self.after,
            limit=self.limit,
        )
        starts = range(0, len(regulations), _BATCH)
        for start in self._track(starts, "batches of regulations", total=len(starts)):
            batch = regulations[start : start + _BATCH]
            rows = []
            for version in amount_queries.version_texts(self.store, batch):
                found = amounts(
                    version["text"],
                    version.get("parts") or (),
                    version.get("tables") or (),
                    version.get("redactions") or (),
                )
                ids = {"version_id": version["id"], "bwb_id": version["bwb_id"]}
                rows += [ids | amount.to_row() for amount in found]
            result.updated += amount_queries.keep_amounts(self.store, batch, rows)
        last = regulations[-1] if regulations else None
        logger.info(
            "Amounts: %d regulations read, %d rows changed; the last read was %s (go on with "
            "--after %s).",
            len(regulations),
            result.updated,
            last,
            last,
        )
        return result
