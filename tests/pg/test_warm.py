"""The warm-up of the API on a real PostgreSQL: it computes its parts, and says for which
data version it is done (``/api/health`` ``warm``)."""

from __future__ import annotations

import datetime as dt
from functools import partial
from types import SimpleNamespace

import pytest

from lawgraph.api import warm
from lawgraph.core.time import dutch_today
from lawgraph.db import GraphStore
from lawgraph.db.queries import _bm25, warm_nodes
from lawgraph.db.queries.articles import get_article_cited_by
from tests.fakes import ManualClock, until
from tests.pg.plans import recorded


def test_the_warm_up_is_done_for_the_data_as_it_was(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(warm, "_warmed", None)
    assert not warm.is_warm(store.data_version())

    warm.warm_up(store)
    assert warm.is_warm(store.data_version())
    assert warm.warmed_version() == store.data_version()

    store.bulk_insert_or_update_nodes(
        "instruments",
        [{"key": "x", "type": "instrument", "labels": [], "props": {"title": "x"}}],
    )
    assert not warm.is_warm(store.data_version())  # the data changed: warm again


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
            [{"key": "y", "type": "instrument", "labels": [], "props": {}}],
        )

    monkeypatch.setattr(
        warm,
        "PARTS",
        (
            warm.Part("stats", stats_while_a_pipeline_writes),
            warm.Part("coverage", lambda s: asked.append("coverage")),
        ),
    )
    warm.warm_up(store)
    assert asked == ["stats"]  # stopped before the next part
    assert not warm.is_warm(store.data_version())


def test_the_tail_is_warmed_after_the_rest_and_warm_waits_for_it(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``TAIL`` runs after ``PARTS``, each in its order, not beside them: the disk is what
    the warm-up waits for. The warm-up is done (``warm``) only when the last part of the
    tail is, and not when newer data arrives during it."""
    monkeypatch.setattr(warm, "_warmed", None)
    ran: list[str] = []
    warm_then: list[bool] = []

    def part(name: str):
        def run(store_: GraphStore) -> None:
            ran.append(name)
            warm_then.append(warm.is_warm(store_.data_version()))

        return run

    monkeypatch.setattr(
        warm, "PARTS", (warm.Part("a", part("a")), warm.Part("b", part("b")))
    )
    monkeypatch.setattr(
        warm, "TAIL", (warm.Part("t1", part("t1")), warm.Part("t2", part("t2")))
    )
    monkeypatch.setattr(warm, "_warm_articles", lambda *args: None)
    monkeypatch.setattr(warm, "_warm_search_terms", lambda store_: None)
    warm.warm_up(store)
    assert ran == ["a", "b", "t1", "t2"]
    assert warm_then == [False] * 4
    assert warm.is_warm(store.data_version())

    def writes(store_: GraphStore) -> None:
        store_.bulk_insert_or_update_nodes(
            "instruments",
            [{"key": "t", "type": "instrument", "labels": [], "props": {}}],
        )

    monkeypatch.setattr(
        warm, "TAIL", (warm.Part("t1", writes), warm.Part("t2", part("t2")))
    )
    monkeypatch.setattr(warm, "PARTS", ())
    monkeypatch.setattr(warm, "_warmed", None)
    ran.clear()
    warm.warm_up(store)
    assert "t2" not in ran  # the tail stopped: the data changed
    assert warm.warmed_version() is None


def test_the_warm_up_counts_the_largest_areas_of_law(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first page of an area of law counts its facets over all its judgments."""
    areas = [{"value": f"Area {n}", "count": 10 - n} for n in range(7)]
    asked: list[str | None] = []
    sources: list[str | None] = []

    def listed(store_: GraphStore, filters, limit: int = 20):
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
    search_stats.merge_day(tmp_path, dutch_today().isoformat(), counts)
    warm._warm_search_terms(store)
    assert searched == [f"term {n}" for n in range(warm.WARM_SEARCH_TERMS)]


def test_the_warm_up_leaves_a_word_most_judgments_hold(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Its search would rank every judgment that holds it: not searched by the warm-up."""
    from collections import Counter

    from lawgraph.core import search_stats
    from tests.pg.search_graph import judgments_with_words

    judgments_with_words(store, 2000)
    searched: list[str] = []
    monkeypatch.setattr(warm, "search_all", lambda store_, q, **k: searched.append(q))
    monkeypatch.setattr(warm, "SEARCH_STATS_DIR", tmp_path)
    search_stats.merge_day(
        tmp_path,
        dutch_today().isoformat(),
        Counter({"beroep": 30, "zeldzaamheid": 20, "beroep zeldzaamheid": 10}),
    )
    share = partial(_bm25.common_share, store, "judgments", "summary")
    assert share(["beroep"]) > warm.COMMON_SHARE
    assert share(["zeldzaamheid"]) <= warm.COMMON_SHARE
    warm._warm_search_terms(store)
    # every word of the last must be held, so it is as rare as its rarest word
    assert searched == ["zeldzaamheid", "beroep zeldzaamheid"]


def test_a_write_waits_for_the_least_time_between_two_warm_ups(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On a real database: a write raises the data version, and the warm-up of the new
    data waits until ``LAWGRAPH_WARM_UP_MIN_INTERVAL`` has gone by since the last began."""
    from lawgraph.db import version_cache

    clock = ManualClock()
    interval = 1.0
    done: list[tuple[float, str]] = []
    monkeypatch.setattr(version_cache, "_clock", clock)
    monkeypatch.setattr(version_cache, "VERSION_TTL", 0)
    monkeypatch.setattr(version_cache, "WARM_UP_SETTLE", 0.05)
    monkeypatch.setattr(version_cache, "WARM_UP_MIN_INTERVAL", interval)
    monkeypatch.setattr(
        version_cache,
        "_warmers",
        [lambda s: done.append((clock.now(), s.data_version()))],
    )

    version_cache._version(store)  # the version this process knows
    version_cache.warm(store, settle=0)
    assert until(lambda: len(done) == 1)
    store.bulk_insert_or_update_nodes(
        "instruments",
        [{"key": "z", "type": "instrument", "labels": [], "props": {"title": "z"}}],
    )
    version_cache._version(store)  # a request sees the new version: a warm-up is wanted
    assert version_cache.computing(store)  # it waits, and health says so
    clock.move_to_wait(interval)  # not the settle: it is held back
    assert until(lambda: len(done) == 2)
    assert done[1][0] - done[0][0] == pytest.approx(interval)
    assert done[1][1] == store.data_version()  # of the new data


def test_the_terms_searched_most_are_searched_at_most_once_an_hour(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Their search reads pages into the memory of the database and keeps their document
    frequencies per data version: a warm-up after a poll that wrote leaves them when they
    were searched less than an hour ago."""
    searched: list[int] = []
    monkeypatch.setattr(warm, "_warm_search_terms", lambda s: searched.append(1))
    warm.warm_up(store)
    assert searched == [1]  # the first warm-up of the process

    store.bulk_insert_or_update_nodes(
        "judgments",
        [{"key": "poll", "type": "judgment", "labels": [], "props": {"title": "p"}}],
    )
    warm.warm_up(store)  # a poll wrote: everything else is warmed again
    assert warm.is_warm(store.data_version())
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

    def recorded(name: str, part) -> bool:
        ran.append(name)
        return run(name, part)

    monkeypatch.setattr(warm, "_run", recorded)
    warm.warm_up(store)
    assert {"coverage", "instruments"} <= set(ran)

    ran.clear()
    store.bulk_insert_or_update_nodes(
        "judgments",
        [{"key": "poll", "type": "judgment", "labels": [], "props": {"title": "p"}}],
    )
    warm.warm_up(store)
    assert "coverage" in ran
    assert "instruments" not in ran and "search instruments" not in ran
    assert warm.is_warm(store.data_version())

    ran.clear()
    store.bulk_insert_or_update_nodes(
        "instruments",
        [{"key": "x", "type": "instrument", "labels": [], "props": {"title": "x"}}],
    )
    warm.warm_up(store)
    assert "instruments" in ran and "coverage" not in ran


def test_the_articles_cited_most_are_warmed_to_the_last(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The articles cited ``WARM_ARTICLE_CITATIONS`` times or more, the most cited first,
    and all of them also when a pipeline writes meanwhile: the part takes up to half an
    hour, and stopped at every poll it was never done (16 Oct)."""
    at_least = warm_nodes.WARM_ARTICLE_CITATIONS
    store.bulk_insert_or_update_nodes(
        "articles",
        [{"key": key, "type": "article", "labels": [],
          "props": {"inbound_citation_count": n}}
         for key, n in (("low", at_least - 1), ("top", at_least * 9),
                        ("next", at_least * 2), ("last", at_least))],
    )  # fmt: skip
    opened: list[str] = []

    def node(store_: GraphStore, collection: str, key: str) -> None:
        opened.append(key)
        if key == "next":  # a pipeline writes while it is warmed
            store_.bulk_insert_or_update_nodes(
                "instruments",
                [{"key": "z", "type": "instrument", "labels": [], "props": {}}],
            )

    monkeypatch.setattr(warm_nodes, "get_node_with_neighbors", node)
    monkeypatch.setattr(warm_nodes, "get_article_cited_by", lambda *a, **k: None)
    warm._warm_articles(store)
    assert opened == ["top", "next", "last"]


def test_the_articles_are_warmed_at_most_once_an_hour(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A poll every half hour does not start the part of up to half an hour again: a
    warm-up after one leaves the articles when it began them less than
    ``ARTICLES_EVERY`` ago."""
    warmed: list[int] = []
    monkeypatch.setattr(warm, "_warm_articles", lambda store_: warmed.append(1))
    monkeypatch.setattr(warm, "_warm_search_terms", lambda store_: None)
    warm.warm_up(store)
    assert warmed == [1]

    store.bulk_insert_or_update_nodes(
        "judgments",
        [{"key": "poll", "type": "judgment", "labels": [], "props": {"title": "p"}}],
    )
    warm.warm_up(store)  # a poll wrote: everything else is warmed again
    assert warm.is_warm(store.data_version())
    assert warmed == [1]

    monkeypatch.setattr(warm, "ARTICLES_EVERY", 0.0)  # an hour later
    warm.warm_up(store)
    assert warmed == [1, 1]


def test_the_articles_are_warmed_after_the_warm_up_is_done(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A deploy waits for ``warm`` (``/api/health``); the most cited articles take minutes
    and are not waited for: the warm-up is done for the data before they are warmed."""
    monkeypatch.setattr(warm, "_warmed", None)
    warm_while_warming: list[bool] = []
    monkeypatch.setattr(
        warm,
        "_warm_articles",
        lambda store_: warm_while_warming.append(warm.is_warm(store_.data_version())),
    )
    warm.warm_up(store)
    assert warm_while_warming == [True]


def test_the_list_of_every_judgment_is_warmed(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The judgments of every source (the list once its source is cleared) have their
    total and facets kept by the warm-up: a request reads its page alone (its counts over
    every judgment took 20 s cold on prod on 10 Oct)."""
    from lawgraph.db.queries.judgments import JudgmentFilters, get_judgments_list

    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            {"key": f"j{n}", "type": "judgment", "labels": [],
             "props": {"ecli": f"ECLI:NL:HR:2020:{n}", "source": "rechtspraak",
                       "date_eff": "2020-01-01", "tier": "hoogste"}}
            for n in range(5)
        ],
    )  # fmt: skip
    warm.warm_up(store)
    calls = recorded(store, monkeypatch)
    found = get_judgments_list(store, JudgmentFilters(), limit=20)
    seen = [c.text for c in calls]
    assert found["total"] == 5 and found["facets"]
    assert not [s for s in seen if "GROUP BY" in s or "count(*)" in s]


def test_the_summary_of_the_homepage_is_warmed(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The homepage asks the summary of the last two weeks first (its Actueel): after a
    poll the warm-up computes it, and a visitor reads none of it (15 Oct on prod: a 503
    after 30 s while the warm-up read)."""
    from fastapi.testclient import TestClient

    from lawgraph.api.app import app
    from lawgraph.api.dependencies import get_store
    from lawgraph.core import time

    warm.warm_up(store)
    calls = recorded(store, monkeypatch)
    app.dependency_overrides[get_store] = lambda: store
    try:
        response = TestClient(app).get(
            "/api/feed/summary",
            params={
                "until": time.dutch_today().isoformat(),
                "days": warm.HOME_SUMMARY["days"],
                "limit": warm.HOME_SUMMARY["limit"],
            },
        )
    finally:
        app.dependency_overrides.pop(get_store, None)
    assert response.status_code == 200, response.text
    assert not [c for c in calls if "day_kinds" in c.text]


def test_the_homepage_summary_is_of_the_dutch_day(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """At 22:30 UTC in summer it is the next day for a Dutch visitor: the summary the
    homepage asks then (its ``until`` that day, or none) is the one the warm-up kept."""
    from fastapi.testclient import TestClient

    from lawgraph.api.app import app
    from lawgraph.api.dependencies import get_store
    from lawgraph.core import time

    late = dt.datetime(2026, 10, 15, 22, 30, tzinfo=dt.UTC)
    monkeypatch.setattr(time, "_now", lambda: late)
    warm.warm_up(store)
    calls = recorded(store, monkeypatch)
    params = {"days": warm.HOME_SUMMARY["days"], "limit": warm.HOME_SUMMARY["limit"]}
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        default = client.get("/api/feed/summary", params=params)
        asked = client.get(
            "/api/feed/summary", params={**params, "until": "2026-10-16"}
        )
    finally:
        app.dependency_overrides.pop(get_store, None)
    assert default.json()["until"] == asked.json()["until"] == "2026-10-16"
    assert not [c for c in calls if "day_kinds" in c.text]


def test_the_warm_up_asks_the_first_pages_of_the_explorer(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every page the warm-up asks is one ``first-pages.json`` names (the explorer's file):
    an answer is kept per page, so a page of another size is never read from it."""
    import json

    from lawgraph.config.constants import DATA_DIR

    first = json.loads((DATA_DIR / "first-pages.json").read_text("utf-8"))
    asked: list[tuple[str, str | None, int]] = []

    def spy(name: str, real, module=warm):
        def asking(*args, **kwargs):
            asked.append((name, kwargs.get("sort"), kwargs["limit"]))
            return real(*args, **kwargs)

        monkeypatch.setattr(module, name, asking)

    spy("get_article_cited_by", get_article_cited_by, warm_nodes)
    for name in (
        "get_citing_judgments",
        "get_instruments_list",
        "list_documents",
        "get_judgments_list",
        "get_feed",
        "get_feed_summary",
    ):
        spy(name, getattr(warm, name))
    # one article and one law that are cited most, whose pages are warmed too
    for module in (warm, warm_nodes):
        monkeypatch.setattr(
            module,
            "most_cited_articles",
            lambda s, n: [{"key": "a", "id": "articles/a"}],
        )
    monkeypatch.setattr(warm, "most_cited_laws", lambda s, n: ["BWBR0001"])
    monkeypatch.setattr(warm_nodes, "get_node_with_neighbors", lambda *args: None)
    monkeypatch.setattr(warm, "get_node_neighborhood", lambda *a, **k: None)
    monkeypatch.setattr(warm, "_warm_search_terms", lambda store_: None)
    warm.warm_up(store)

    lists = first["lists"]
    names = first["instrument_names"]
    assert sorted(set(asked), key=str) == sorted(
        {
            *(("get_article_cited_by", p["sort"], p["limit"])
              for p in first["article_citations"]),
            ("get_citing_judgments", None, first["law_judgments"]),
            ("get_instruments_list", None, lists["instruments"]),
            ("get_instruments_list", names["sort"], names["limit"]),
            ("get_instruments_list", None, 1),  # the facets of Bladeren
            ("list_documents", None, lists["documents"]),
            ("get_judgments_list", None, lists["judgments"]),
            ("get_judgments_list", None, 1),  # the areas of law, by their facet
            ("get_feed", None, lists["feed"]),
            ("get_feed_summary", None, first["home_summary"]["limit"]),
        },
        key=str,
    )  # fmt: skip


def _seed_cited(store: GraphStore, counts: dict[str, int]) -> None:
    store.bulk_insert_or_update_nodes(
        "articles",
        [{"key": key, "type": "article", "labels": [],
          "props": {"inbound_citation_count": n}} for key, n in counts.items()],
    )  # fmt: skip


def test_the_neighborhoods_of_the_articles_cited_most_are_walked_as_the_canvas_asks(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The neighbourhood of each article cited ``WARM_ARTICLE_CITATIONS`` times or more,
    the most cited first, as the canvas of the explorer asks it (``article_neighborhood``
    of ``first-pages.json``): 6:162 BW took 7.5 s cold on prod (27 Oct), 0.3 s warm. The
    same request is one the route takes."""
    from fastapi.testclient import TestClient

    from lawgraph.api.app import app
    from lawgraph.api.dependencies import get_store

    at_least = warm_nodes.WARM_ARTICLE_CITATIONS
    _seed_cited(store, {"low": at_least - 1, "top": at_least * 9, "next": at_least})
    page = warm_nodes.FIRST_PAGES["article_neighborhood"]
    walked: list[tuple[str, dict]] = []
    from lawgraph.db.queries.nodes import get_node_neighborhood as real

    def walk(store_: GraphStore, collection: str, key: str, **kwargs):
        walked.append((key, kwargs))
        return real(store_, collection, key, **kwargs)

    monkeypatch.setattr(warm, "get_node_neighborhood", walk)
    warm._warm_neighborhoods(store)
    assert [key for key, _ in walked] == ["top", "next"]
    asked = walked[0][1]
    assert (asked["depth"], asked["cap"], asked["canvas"]) == (
        page["depth"], page["cap"], page["props"] == "canvas"
    )  # fmt: skip
    assert asked["filters"].node_types == tuple(page["node_types"])
    assert tuple(asked["stop_at"]) == tuple(page["stop_at"])

    app.dependency_overrides[get_store] = lambda: store
    try:
        answer = TestClient(app).get(
            "/api/nodes/articles/top/neighborhood",
            params={**page, "node_types": ",".join(page["node_types"]),
                    "stop_at": ",".join(page["stop_at"])},
        )  # fmt: skip
    finally:
        app.dependency_overrides.pop(get_store, None)
    assert answer.status_code == 200, answer.text


def test_the_neighborhoods_are_walked_for_a_bounded_time(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The neighbourhoods stop once ``NEIGHBORHOODS_FOR`` has passed, the most cited
    walked first: what they read stays in the memory of the database only while it has
    room, and the hour is shared with the rest."""
    at_least = warm_nodes.WARM_ARTICLE_CITATIONS
    _seed_cited(store, {"top": at_least * 9, "next": at_least * 2, "last": at_least})
    clock = ManualClock()
    monkeypatch.setattr(warm, "time", SimpleNamespace(monotonic=clock.now))
    walked: list[str] = []

    def walk(store_: GraphStore, collection: str, key: str, **kwargs) -> None:
        walked.append(key)
        clock.advance(warm.NEIGHBORHOODS_FOR / 2 + 1)

    monkeypatch.setattr(warm, "get_node_neighborhood", walk)
    warm._warm_neighborhoods(store)
    assert walked == ["top", "next"]


def test_the_neighborhoods_are_warmed_after_the_articles_once_an_hour(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After the passages of the most cited articles, at most once per
    ``ARTICLES_EVERY``, as they are."""
    ran: list[str] = []
    monkeypatch.setattr(warm, "_warm_articles", lambda store_: ran.append("articles"))
    monkeypatch.setattr(
        warm, "_warm_neighborhoods", lambda store_: ran.append("neighborhoods")
    )
    monkeypatch.setattr(warm, "_warm_search_terms", lambda store_: None)
    warm.warm_up(store)
    warm.warm_up(store)
    assert ran == ["articles", "neighborhoods"]
