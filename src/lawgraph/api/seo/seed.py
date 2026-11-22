"""The API answer the app asks first of a page, given in its HTML (``#api-seed``): the
explorer keeps it under the key it keeps that answer by (``once`` of ``api/records.ts``)
and asks nothing. Of an article only: its ``/api/articles/{law}/{number}``
(``getArticleDetail``), as that route answers it.

Within ``SEED_BUDGET``: past it the page goes without, and the app asks the route.
"""

from __future__ import annotations

from lawgraph.api.params import article_ref
from lawgraph.api.routes.articles import get_article_detail
from lawgraph.api.seo.preload import article_address
from lawgraph.core.readable_paths import Pad
from lawgraph.db import GraphStore
from lawgraph.db.queries.not_found import NotFound

# The seconds the read of the seed may take: past them the page goes without it.
SEED_BUDGET = 0.15

# The key ``getArticleDetail`` keeps its answer by (``articles/${bwbId}/${articleNumber}``):
# no node id, the path of its route.
_ARTICLE_KEY = "articles/{law}/{number}"


def article_seed(store: GraphStore, pad: Pad) -> dict[str, str]:
    """The answer of ``/api/articles/{law}/{number}`` for the article at *pad*, as JSON
    under the key ``once`` keeps it by (``articles/<law>/<number>``, in lower case); none
    where the route has no article."""
    law, number = article_address(pad)
    try:
        detail = get_article_detail(article_ref(law, number), store)
    except NotFound:
        return {}
    key = _ARTICLE_KEY.format(law=law, number=number).lower()
    return {key: detail.model_dump_json(by_alias=True)}
