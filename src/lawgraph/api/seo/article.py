"""What the page of an article reads (``db.queries.seo.article``) and what it has besides:
its versions, as its history lists them, and the first ``CHAIN`` regulations based on it.
Those two each within ``EXTRA_BUDGET``: past it the page goes without that block (None), as
it does without the judgments citing it; its first paint reads the versions read here.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from lawgraph.api.seo.paint import article_versions
from lawgraph.db import GraphStore
from lawgraph.db.queries import seo
from lawgraph.db.queries.delegations import delegated_first
from lawgraph.db.request_context import read_budget

# The regulations based on an article its page names, the AMvB's first: the most of an
# article in the Awb are hundreds (4:81: 323, mostly ministerial regulations and policy
# rules), the rest a link to the app away.
CHAIN = 10
# The seconds the versions of an article and the regulations based on it may take each:
# about 15 to 45 ms of the versions (30 Oct, lawgraph_small), 0.1 to 0.4 s of every
# regulation under 4:81 on prod before ``CHAIN`` capped it.
EXTRA_BUDGET = 0.15


def article(store: GraphStore, node_id: str) -> dict[str, Any] | None:
    """The row of ``seo.article`` with ``versions`` (``paint.article_versions``) and
    ``delegated`` (``delegations.delegated_first``), each None past ``EXTRA_BUDGET``."""
    row = seo.article(store, node_id)
    if row is None:
        return None
    return {
        **row,
        "versions": _within(lambda: article_versions(store, row), "Versions of a page"),
        "delegated": _within(
            lambda: delegated_first(store, node_id, CHAIN), "Regulations of a page"
        ),
    }


def _within[T](read: Callable[[], T], what: str) -> T | None:
    found: T | None = None
    with read_budget(EXTRA_BUDGET, what) as budget:
        found = read()
    return None if budget.ran_out else found
