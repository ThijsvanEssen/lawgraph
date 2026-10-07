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

    def stats_while_a_pipeline_writes(store_: GraphStore) -> None:
        asked.append("stats")
        store_.bulk_insert_or_update_nodes(
            "instruments",
            [{"_key": "y", "type": "instrument", "labels": [], "props": {}}],
        )

    monkeypatch.setattr(warm, "stats_data", stats_while_a_pipeline_writes)
    monkeypatch.setattr(warm, "coverage_data", lambda s: asked.append("coverage"))
    warm.warm_up(store)
    assert asked == ["stats"]  # stopped before the next part
    assert not warm.is_warm(store)


def test_the_heat_is_counted_after_the_warm_up_is_done(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It reads every edge: ``warm`` never waits for it, and the first visitor of the heat
    finds it computed."""
    warm_when_counted: list[bool] = []

    def heat(store_: GraphStore) -> dict[str, int]:
        warm_when_counted.append(warm.is_warm(store_))
        return {}

    monkeypatch.setattr(warm, "heat_counts", heat)
    monkeypatch.setattr(warm, "_warmed", None)
    warm.warm_up(store)
    assert warm_when_counted == [True]


def test_the_warm_up_counts_the_largest_areas_of_law(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first page of an area of law counts its facets over all its judgments."""
    areas = [{"value": f"Area {n}", "count": 10 - n} for n in range(7)]
    asked: list[str | None] = []
    sources: list[str | None] = []

    def listed(store_: GraphStore, filters, limit: int = 20):  # type: ignore[no-untyped-def]
        asked.append(filters.subject_area)
        sources.append(filters.source)
        return {"total": 0, "items": [], "facets": {"subject_area": areas}}

    monkeypatch.setattr(warm, "get_judgments_list", listed)
    warm._warm_subject_areas(store)
    assert asked == [None, "Area 0", "Area 1", "Area 2", "Area 3", "Area 4"]
    # with the filters the front end sends, whose facets are kept per filter
    assert sources == ["rechtspraak"] * 6


def test_the_warm_up_searches_the_terms_searched_most(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """At most ``WARM_SEARCH_TERMS``, each asked ``MIN_COUNT`` times or more; none without
    counts."""
    import datetime as dt
    from collections import Counter

    from lawgraph.core import search_stats

    searched: list[str] = []
    monkeypatch.setattr(warm, "search_all", lambda store_, q, **k: searched.append(q))
    monkeypatch.setattr(warm, "SEARCH_STATS_DIR", tmp_path / "none")
    warm._warm_search_terms(store)
    assert searched == []  # no counts: nothing searched

    monkeypatch.setattr(warm, "SEARCH_STATS_DIR", tmp_path)
    counts = Counter({f"term {n}": 20 - n for n in range(8)})
    counts["rechtszaak jansen"] = 2  # asked too rarely: never searched by the warm-up
    search_stats.merge_day(tmp_path, dt.date.today().isoformat(), counts)
    warm._warm_search_terms(store)
    assert searched == [f"term {n}" for n in range(warm.WARM_SEARCH_TERMS)]
