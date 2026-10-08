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


def test_a_write_waits_for_the_least_time_between_two_warm_ups(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On a real database: a write raises the data version, and the warm-up of the new
    data waits until ``LAWGRAPH_WARM_UP_MIN_INTERVAL`` has gone by since the last began."""
    import time

    from lawgraph.db import version_cache

    done: list[tuple[float, str]] = []
    monkeypatch.setattr(version_cache, "VERSION_TTL", 0)
    monkeypatch.setattr(version_cache, "WARM_UP_SETTLE", 0.05)
    monkeypatch.setattr(version_cache, "WARM_UP_MIN_INTERVAL", 1.0)
    monkeypatch.setattr(
        version_cache,
        "_warmers",
        [lambda s: done.append((time.monotonic(), s.data_version()))],
    )

    def until(count: int, seconds: float) -> bool:
        end = time.monotonic() + seconds
        while time.monotonic() < end and len(done) < count:
            time.sleep(0.02)
        return len(done) >= count

    version_cache._version(store)  # the version this process knows
    version_cache.warm(store, settle=0)
    assert until(1, 2.0)
    store.bulk_insert_or_update_nodes(
        "instruments",
        [{"_key": "z", "type": "instrument", "labels": [], "props": {"title": "z"}}],
    )
    version_cache._version(store)  # a request sees the new version: a warm-up is wanted
    assert version_cache.computing(store)  # it waits, and health says so
    assert not until(2, 0.6)
    assert until(2, 2.0)
    assert done[1][0] - done[0][0] >= 1.0
    assert done[1][1] == store.data_version()  # of the new data
