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
    assert warm.warmed_version() == store.data_version()

    store.bulk_insert_or_update_nodes(
        "instruments",
        [{"_key": "x", "type": "instrument", "labels": [], "props": {"title": "x"}}],
    )
    assert not warm.is_warm(store)  # the data changed: warm again


def test_a_warm_up_stops_when_newer_data_arrives(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Between its parts the warm-up asks whether the data changed; it stops then, and is
    not done for the old version."""
    monkeypatch.setattr(warm, "_warmed", None)
    asked: list[str] = []

    def judgments_while_a_pipeline_writes(store_: GraphStore, *a, **k) -> None:
        asked.append("judgments")
        store_.bulk_insert_or_update_nodes(
            "instruments",
            [{"_key": "y", "type": "instrument", "labels": [], "props": {}}],
        )

    monkeypatch.setattr(warm, "get_judgments_list", judgments_while_a_pipeline_writes)
    monkeypatch.setattr(
        warm, "load_notation_parser", lambda s: asked.append("search notation")
    )
    warm.warm_up(store)
    assert asked == ["judgments"]  # stopped before the next part
    assert not warm.is_warm(store)


def test_the_warm_up_leaves_the_heat_of_the_whole_graph(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It reads every edge: ``warm`` never waits for it."""
    from lawgraph.api.routes import nodes
    from lawgraph.db.queries import overlay

    def no_heat(*args, **kwargs):  # type: ignore[no-untyped-def]
        pytest.fail("the warm-up counted the heat")

    monkeypatch.setattr(nodes, "get_heat_tops", no_heat)
    monkeypatch.setattr(overlay, "get_heat_tops", no_heat)
    monkeypatch.setattr(warm, "_warmed", None)
    warm.warm_up(store)
    assert warm.is_warm(store)
