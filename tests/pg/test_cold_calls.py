"""Calls the explorer makes when it opens a network, asked cold (26 Oct, prod: 6 to 10 s):
a rarely cited article must not queue behind the workers of the cache, which a warm-up
holds for minutes, and the dossiers of a faction (every paper of its members) are warmed."""

from __future__ import annotations

import time

import pytest

from lawgraph.api import warm
from lawgraph.api.routes.factions import faction_dossiers
from lawgraph.db import GraphStore, version_cache
from lawgraph.db.queries.articles import get_article_cited_by
from tests.pg.plans import pool_busy, recorded

ARTICLE = "articles/bwbr0005416_146"


def _seed_citation(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "articles",
        [{"key": "bwbr0005416_146", "type": "article", "labels": [],
          "props": {"article_number": "146", "inbound_citation_count": 1}}],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "judgments",
        [{"key": "j1", "type": "judgment", "labels": ["Rechtspraak"],
          "props": {"ecli": "ECLI:NL:HR:2020:1", "source": "rechtspraak",
                    "court_code": "HR", "tier": "hoge_raad", "date_eff": "2020-01-01"}}],
    )  # fmt: skip
    store.bulk_insert_or_update_edges(
        [{"key": "e1", "from_id": "judgments/j1", "to_id": ARTICLE,
          "relation": "REFERS_TO", "meta": {"mentions": [{"leden": ["1"]}]}}]
    )  # fmt: skip


def test_a_rarely_cited_article_does_not_wait_for_the_workers_of_the_cache(
    store: GraphStore,
) -> None:
    """Its passages are a range of an index: computed in the request, so a pool held by a
    warm-up (``pool_busy``) does not hold the request (it waited 7 s on prod)."""
    _seed_citation(store)
    version_cache.clear()
    with pool_busy():
        began = time.monotonic()
        cited_by = get_article_cited_by(store, ARTICLE, tiers=("hoge_raad",), limit=1)
        assert time.monotonic() - began < 5
    assert cited_by.total == 1 and cited_by.facets["tier"][0]["value"] == "hoge_raad"


def test_the_warm_up_keeps_the_dossiers_of_each_faction_of_today(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.bulk_insert_or_update_nodes(
        "factions",
        [{"key": key, "type": "faction", "labels": [],
          "props": {"name": key.upper(), "abbreviation": key.upper(),
                    "active": True}}
         for key in ("vvd", "d66")],
    )  # fmt: skip
    version_cache.clear()
    warm._warm_faction_dossiers(store)
    reads = recorded(store, monkeypatch, "_stream")
    for key in ("vvd", "d66"):
        page = faction_dossiers(store, f"factions/{key}", 100, 0, "opened")
        assert page.items == []
    # kept: only the versions of the tables are read
    assert [c.text for c in reads if "lg_data_version" not in c.text] == []
