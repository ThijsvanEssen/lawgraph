"""Warm the node of the most cited articles: its edges, their lid counts and the first pages
of its citing passages, as the explorer asks them (``GET /api/nodes/articles/{key}`` and
``…/cited-by``).

Both the API's warm-up (``api/warm.py``) and the pipelines' end (``graph-steps``) call it:
the API when it starts and keeps the answers in its own memory, the pipeline after the
nightly's work has pushed the pages of these articles out of the memory of the database, so
that the first visitor of 6:162 BW does not read the 9,000 edges of it from disk (cold 3–18 s
on prod, 28 Oct; warm 0.17 s).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

import psycopg

from lawgraph.config.constants import COLLECTION_ARTICLES, DATA_DIR
from lawgraph.core.logging import get_logger
from lawgraph.db import GraphStore
from lawgraph.db.queries.articles import (
    CITED_BY_INLINE_BELOW,
    get_article_cited_by,
    most_cited_articles,
)
from lawgraph.db.queries.nodes import get_node_with_neighbors

logger = get_logger(__name__)

# The pages the explorer asks first, by their size and order (``data/first-pages.json``, a
# copy of the explorer's): a warm-up asks exactly these, as an answer is kept per page.
FIRST_PAGES: dict[str, Any] = json.loads(
    (DATA_DIR / "first-pages.json").read_text("utf-8")
)

# The articles whose node and citing passages are warmed: those cited so often that they
# open in more than a second cold (1,500 citations or more were 335 articles on prod).
WARM_ARTICLE_CITATIONS = CITED_BY_INLINE_BELOW
# How long the pipelines' end warms them at most (seconds), the most cited first.
WARM_NODES_FOR = 300.0
# The most cited articles the API always warms in full, also when newer data arrives:
# those visited most.
WARM_ARTICLES_FIRST = 20


def warm_articles(
    store: GraphStore,
    seconds: float | None = None,
    *,
    first: int = 0,
    stopped: Callable[[], bool] = lambda: False,
) -> int:
    """The node and the first citing passages of each article cited
    ``WARM_ARTICLE_CITATIONS`` times or more, the most cited first: the *first* in full,
    then until *seconds* have passed (no limit without) or *stopped* holds. How many were
    warmed."""
    stop = None if seconds is None else time.monotonic() + seconds
    articles = most_cited_articles(store, WARM_ARTICLE_CITATIONS)
    for done, article in enumerate(articles):
        if done >= first and (
            (stop is not None and time.monotonic() >= stop) or stopped()
        ):
            logger.info(
                "Warm-up of the nodes stopped at %s: %d of %d articles warmed.",
                article["key"],
                done,
                len(articles),
            )
            return done
        get_node_with_neighbors(store, COLLECTION_ARTICLES, article["key"])
        for page in FIRST_PAGES["article_citations"]:
            get_article_cited_by(
                store, article["id"], sort=page["sort"], limit=page["limit"]
            )
    logger.info("Warm-up of the nodes done: %d articles warmed.", len(articles))
    return len(articles)


def warm_most_cited_nodes(store: GraphStore) -> None:
    """``warm_articles`` for ``WARM_NODES_FOR``; a failure costs only the warmth."""
    try:
        warm_articles(store, WARM_NODES_FOR)
    except psycopg.Error:
        logger.warning(
            "Reading the most cited articles to warm them failed.", exc_info=True
        )
