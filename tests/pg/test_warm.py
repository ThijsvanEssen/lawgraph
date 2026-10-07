"""The warm-up of the API on a real PostgreSQL: it computes its parts, and says for which
data version it is done (``/api/health`` ``warm``)."""

from __future__ import annotations

import pytest

from lawgraph.api import warm
from lawgraph.db import GraphStore


def test_the_warm_up_is_done_for_the_data_as_it_was(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(warm, "_warmed", None)
    assert not warm.is_warm(store)

    warm.warm_up(store)
    assert warm.is_warm(store)

    store.bulk_insert_or_update_nodes(
        "instruments",
        [{"_key": "x", "type": "instrument", "labels": [], "props": {"title": "x"}}],
    )
    assert not warm.is_warm(store)  # the data changed: warm again
