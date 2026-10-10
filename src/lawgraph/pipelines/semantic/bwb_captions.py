"""``semantic bwb-captions``: what each article is about, for its title.

Of each regulation the breadcrumbs of its articles are read (no XML, no text) and every
article keeps its ``caption`` (``core.article_caption``): the deepest title of the divisions it
stands in that one division of the law has. The title of an article in the API and in the
server HTML names it: ``Art. 6:162 BW, Onrechtmatige daad``. Only a caption that changed is
written.

``--since``: the regulations whose toestand was fetched since then (the daily run). Without it
every one, in slices if need be: ``--after BWB-ID`` starts past that regulation, ``--limit
N`` stops after N, and the log names the last one read.
"""

from __future__ import annotations

import datetime as dt
from itertools import groupby

from lawgraph.config.constants import COLLECTION_ARTICLES
from lawgraph.core.article_caption import captions
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult
from lawgraph.core.time import iso_timestamp
from lawgraph.db import NodeWriter
from lawgraph.db.queries.semantic import bwb as semantic_bwb
from lawgraph.db.store import GraphStore

from .base import SemanticPipelineBase

logger = get_logger(__name__)

# Regulations read at a time.
_BATCH = 200


class BWBCaptionsSemanticPipeline(SemanticPipelineBase):
    """The caption of every article of the regulations read, on the article."""

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
        with_caption = 0
        starts = range(0, len(regulations), _BATCH)
        for start in self._track(starts, "batches of regulations", total=len(starts)):
            batch = regulations[start : start + _BATCH]
            rows = semantic_bwb.article_breadcrumbs(self.store, batch)
            changed = []
            for _, articles in groupby(rows, key=lambda row: row["bwb_id"]):
                found = list(articles)
                kept = {row["key"]: row.get("caption") for row in found}
                for key, caption in captions(found).items():
                    with_caption += caption is not None
                    if caption != kept.get(key):
                        changed.append(
                            Node(
                                collection=COLLECTION_ARTICLES,
                                type=NodeType.ARTICLE,
                                key=key,
                                labels=[],
                                props={"caption": caption},
                                _skip_validation=True,
                            )
                        )
            with NodeWriter(self.store) as writer:
                writer.add_all(changed)
            result.updated += len(changed)
        last = regulations[-1] if regulations else None
        logger.info(
            "Captions: %d regulations read, %d articles with a caption, %d changed; the "
            "last read was %s (go on with --after %s).",
            len(regulations),
            with_caption,
            result.updated,
            last,
            last,
        )
        return result
