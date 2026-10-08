"""``lawgraph semantic graph-article-terms``: what the judgments that cite an article call it.

Keeps per article its terms (``db/queries/article_terms.py``): the stems that recur in the
summaries of its citing judgments more than in all summaries, so that a search for
"noodweer" finds art. 41 Sr. Reads the light summaries (``lg_judgment_light``) and the
citing edges, never a judgment's text. Without ``--touched-since`` it counts the stems of
every summary once and keeps the terms of every article cited often enough; with it, the
terms of the articles a judgment cited since then, weighed against the counts of the last
whole run. A batch of articles at a time, each written on its own: a run stopped halfway
keeps what it wrote, and a run again writes only what changed. Raises the data version of
``articles`` when terms changed, so the search answers anew.
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
from lawgraph.pipelines.command import add_since_argument, command_parser
from lawgraph.pipelines.semantic._touched import edge_moment

logger = get_logger(__name__)


def run(store: GraphStore, touched_since: dt.datetime | None = None) -> int:
    """Keep the terms of the articles (of those cited since *touched_since*); the articles
    whose terms changed."""
    if touched_since is None:
        counts = count_summary_stems(store)
        logger.info(
            "Counted %d stems in %d light summaries.",
            len(counts.stems),
            counts.judgments,
        )
        articles = cited_articles(store)
        changed = keep_terms(store, articles, counts)
    else:
        articles = articles_cited_since(store, edge_moment(touched_since))
        changed = keep_terms(store, articles)
    logger.info("Kept the terms of %d articles: %d changed.", len(articles), changed)
    if changed:
        raise_articles_version(store)
    return changed


def main(argv: list[str] | None = None) -> PipelineResult:
    parser = command_parser(
        description=(
            "Keep per article the terms the judgments that cite it call it by (noodweer of "
            "art. 41 Sr), which the search finds it by."
        )
    )
    add_since_argument(
        parser,
        "--touched-since",
        help=(
            "Only the articles a judgment cited since this moment (a poll), against the "
            "counts of the last whole run; without it every article. ISO 8601 or "
            "relative ('2h')."
        ),
    )
    args = parser.parse_args(argv)
    return PipelineResult(updated=run(GraphStore(), args.touched_since))
