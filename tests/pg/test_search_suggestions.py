"""What a search that found nothing suggests, on a real PostgreSQL: the words of the titles of
the laws and the dossiers (``load_suggestion_words``) and the answer of ``/api/search``."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.db import GraphStore, version_cache
from lawgraph.db.queries.search.suggestions import load_suggestion_words


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
               title="Crisis- en herstelwet 2024")],
    )  # fmt: skip
    version_cache.clear()
    yield store
    version_cache.clear()


def test_the_words_of_the_titles_of_the_laws_and_dossiers(titled: GraphStore) -> None:
    """Folded, four characters or more, no number, each with the titles that hold it; a
    publication of the Staatsblad is no law."""
    words = load_suggestion_words(titled).words
    assert words == {"coalitie": 1, "coalitiewet": 1, "crisis": 1, "herstelwet": 1}


def test_a_search_that_found_nothing_suggests_its_words_apart(
    titled: GraphStore,
) -> None:
    app.dependency_overrides[get_store] = lambda: titled
    try:
        client = TestClient(app)
        body = client.get("/api/search", params={"q": "coalitiecrisis"}).json()
        assert body["total"] == 0
        assert body["suggestions"][0] == "coalitie crisis"
        # what it suggests finds something
        found = client.get("/api/search", params={"q": "coalitie crisis"}).json()
        assert found["total"] > 0
        assert found["suggestions"] == []
    finally:
        app.dependency_overrides.pop(get_store, None)
