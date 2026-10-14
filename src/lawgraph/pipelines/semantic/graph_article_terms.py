"""``lawgraph semantic graph-article-terms``: what the judgments that cite an article call it.

Keeps per article its terms (``db/queries/article_terms.py``): the stems that recur in the
summaries of its citing judgments more than in all summaries, so that a search for
"noodweer" finds art. 41 Sr. Reads the light summaries (``lg_judgment_light``) and the
citing edges, never a judgment's text. Without ``--since`` it counts the stems of every
summary once and keeps the terms of every article cited often enough (once after a deploy
by hand, and every week in ``weekly.sh``, which keeps the counts fresh); with it (``semantic
all --since``, as ``daily.sh`` runs it) the terms of the articles a judgment cited since
then, weighed against the counts of the last whole run. A batch of articles at a time,
each written on its own: a run stopped halfway keeps what it wrote, and a run again writes
only what changed. Raises the data version of ``articles`` when terms changed, so the
search answers anew.
"""

from __future__ import annotations

import datetime as dt

from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.db import GraphStore
from lawgraph.db.queries.article_terms import (
    articles_cited_since,
    cited_articles,
    count_summary_stems,
    keep_terms,
    raise_articles_version,
)
from lawgraph.pipelines.base import PipelineBase
from lawgraph.pipelines.semantic._touched import edge_moment

logger = get_logger(__name__)


class GraphArticleTermsSemanticPipeline(PipelineBase):
    store: GraphStore

    def run(self, since: dt.datetime | None = None) -> PipelineResult:
        """Keep the terms of the articles (of those cited since *since*); updated: the
        articles whose terms changed."""
        store = self.store
        if since is None:
            counts = count_summary_stems(store)
            logger.info(
                "Counted %d stems in %d light summaries.",
                len(counts.stems),
                counts.judgments,
            )
            articles = cited_articles(store)
            changed = keep_terms(store, articles, counts)
        else:
            articles = articles_cited_since(store, edge_moment(since))
            changed = keep_terms(store, articles)
        logger.info(
            "Kept the terms of %d articles: %d changed.", len(articles), changed
        )
        if changed:
            raise_articles_version(store)
        return PipelineResult(updated=changed)
