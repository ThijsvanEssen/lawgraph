"""The types ``/api/search`` takes are those its searches dispatch on, ranked and live."""

from __future__ import annotations

from typing import Any, cast

from lawgraph.db.queries import search
from lawgraph.db.queries.search import SEARCH_TYPES


def test_the_search_types_are_the_keys_of_the_dispatch() -> None:
    store = cast(Any, None)  # the searches are not run
    full = search._full_searches(store, "q", ["q"], None, None, 10)
    live = search._live_searches(store, "q", ["q"], None, None, 10)
    assert set(full) == set(live) == SEARCH_TYPES
