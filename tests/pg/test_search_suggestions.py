"""What a search that found nothing suggests, on a real PostgreSQL: the names of the concepts
and the words of the titles of the laws and the dossiers (``suggested``) and the answer of
``/api/search``."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.db import GraphStore, version_cache
from lawgraph.db.queries.search.suggestions import suggested


def _node(key: str, node_type: str, **props: Any) -> dict[str, Any]:
    return {"key": key, "type": node_type, "labels": [], "props": props}


@pytest.fixture()
def titled(store: GraphStore) -> Iterator[GraphStore]:
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _node("bwbr0001", "instrument", bwb_id="BWBR0001", kind="wet",
                  title="Wet op de coalitie", citation_title="Coalitiewet"),
            _node("stb-2024-1", "instrument", kind="publicatie",
                  title="Besluit over de coalitie en de staatsblad-zaken"),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "dossiers",
        [_node("36001", "dossier", number="36001", label="36001",
               title="Wet herstel coalitieakkoorden 2024")],
    )  # fmt: skip
    version_cache.clear()
    yield store
    version_cache.clear()


def test_the_names_like_the_query(titled: GraphStore) -> None:
    """A word of the title of a law or a dossier, not of a publication of the Staatsblad;
    a concept by one of its names; nothing like it is nothing."""
    assert suggested(titled, "coalitiewett") == ["coalitiewet"]
    assert suggested(titled, "coalitieakoorden") == ["coalitieakkoorden"]
    assert suggested(titled, "staatsbladzaken") == []
    assert suggested(titled, "wanprestatei") == ["wanprestatie"]
    assert suggested(titled, "Wanprestatie") == []
    assert suggested(titled, "xyzzy") == []


def test_a_search_that_found_nothing_suggests_what_finds_something(
    titled: GraphStore,
) -> None:
    app.dependency_overrides[get_store] = lambda: titled
    try:
        client = TestClient(app)
        body = client.get("/api/search", params={"q": "coalitiewett"}).json()
        assert body["total"] == 0
        assert body["suggestions"] == ["coalitiewet"]
        # what it suggests finds something
        found = client.get("/api/search", params={"q": "coalitiewet"}).json()
        assert found["total"] > 0
        assert found["suggestions"] == []
    finally:
        app.dependency_overrides.pop(get_store, None)
