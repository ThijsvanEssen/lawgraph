"""An article only a citation names (a stub: a number, no text) is no hit of the search,
in the full, the live and the citation search alike."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.config.constants import COLLECTION_ARTICLES
from lawgraph.core.models import make_node_key
from lawgraph.db import GraphStore, version_cache
from lawgraph.db.queries.search import dispatch
from tests.databases import Api

SR = "BWBR0001854"


def _put(store: GraphStore, key: str, **props: Any) -> None:
    doc = {"key": key, "type": "article", "labels": [], "props": props}
    store.bulk_insert_or_update_nodes(COLLECTION_ARTICLES, [doc])


@pytest.fixture()
def seeded(store: GraphStore, monkeypatch: pytest.MonkeyPatch) -> GraphStore:
    monkeypatch.setattr(dispatch, "LIVE_BUDGET", 30.0)
    version_cache.clear()
    _put(
        store,
        make_node_key(SR, "300"),
        bwb_id=SR,
        article_number="300",
        display_name="Art. 300 Sr",
        text="Hij die opzettelijk een ander mishandelt.",
    )
    for number in ("300van", "3000"):
        _put(
            store,
            make_node_key(SR, number),
            bwb_id=SR,
            article_number=number,
            display_name=f"Art. {number} Sr",
            stub=True,
        )
    return store


@pytest.mark.parametrize("mode", ["full", "live"])
@pytest.mark.parametrize("q", ["Art. 300", "300van", "art. 3000 Sr", "Sr"])
def test_a_stub_article_is_no_hit(
    seeded: GraphStore, api: Api, mode: str, q: str
) -> None:
    answer = api.get_json("/api/search", q=q, mode=mode, types="articles")
    keys = [h["key"] for h in answer["results"].get("articles", [])]
    assert make_node_key(SR, "300van") not in keys
    assert make_node_key(SR, "3000") not in keys
