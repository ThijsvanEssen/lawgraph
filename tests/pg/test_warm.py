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


def test_the_warm_up_leaves_a_word_most_judgments_hold(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Its search would rank every judgment that holds it: not searched by the warm-up."""
    import datetime as dt
    from collections import Counter

    from lawgraph.core import search_stats
    from tests.pg.test_search_statistics import _judgments_with_words

    _judgments_with_words(store, 2000)
    searched: list[str] = []
    monkeypatch.setattr(warm, "search_all", lambda store_, q, **k: searched.append(q))
    monkeypatch.setattr(warm, "SEARCH_STATS_DIR", tmp_path)
    search_stats.merge_day(
        tmp_path,
        dt.date.today().isoformat(),
        Counter({"beroep": 30, "zeldzaamheid": 20, "beroep zeldzaamheid": 10}),
    )
    assert warm._common_word(store, "beroep")
    assert not warm._common_word(store, "zeldzaamheid")
    warm._warm_search_terms(store)
    # every word of the last must be held, so it is as rare as its rarest word
    assert searched == ["zeldzaamheid", "beroep zeldzaamheid"]


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


def test_the_terms_searched_most_are_searched_at_most_once_an_hour(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Their search reads pages into the memory of the database and keeps their document
    frequencies per data version: a warm-up after a poll that wrote leaves them when they
    were searched less than an hour ago."""
    searched: list[int] = []
    monkeypatch.setattr(warm, "_warm_search_terms", lambda s: searched.append(1))
    monkeypatch.setattr(warm, "_terms_searched", None)
    warm.warm_up(store)
    assert searched == [1]  # the first warm-up of the process

    store.bulk_insert_or_update_nodes(
        "judgments",
        [{"_key": "poll", "type": "judgment", "labels": [], "props": {"title": "p"}}],
    )
    warm.warm_up(store)  # a poll wrote: everything else is warmed again
    assert warm.is_warm(store)
    assert searched == [1]

    monkeypatch.setattr(warm, "SEARCH_TERMS_EVERY", 0.0)  # an hour later
    warm.warm_up(store)
    assert searched == [1, 1]


def test_a_part_is_left_out_while_its_tables_stand_still(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A poll of judgments warms what reads judgments again, and leaves the list of the
    instruments (``PART_TABLES``)."""
    ran: list[str] = []
    run = warm._run

    def recorded(name: str, part) -> bool:  # type: ignore[no-untyped-def]
        ran.append(name)
        return run(name, part)

    monkeypatch.setattr(warm, "_run", recorded)
    monkeypatch.setattr(warm, "_warmed_parts", {})
    warm.warm_up(store)
    assert {"coverage", "instruments"} <= set(ran)

    ran.clear()
    store.bulk_insert_or_update_nodes(
        "judgments",
        [{"_key": "poll", "type": "judgment", "labels": [], "props": {"title": "p"}}],
    )
    warm.warm_up(store)
    assert "coverage" in ran
    assert "instruments" not in ran and "search instruments" not in ran
    assert warm.is_warm(store)

    ran.clear()
    store.bulk_insert_or_update_nodes(
        "instruments",
        [{"_key": "x", "type": "instrument", "labels": [], "props": {"title": "x"}}],
    )
    warm.warm_up(store)
    assert "instruments" in ran and "coverage" not in ran
