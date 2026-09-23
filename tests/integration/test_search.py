"""Full-text search in Dutch, run for real on the small test server.

The texts are Dutch, so a word must find its other forms: the plural its singular and back
("uitspraken" finds "uitspraak", "wetten" finds "wet"). An English stemmer leaves Dutch
plurals as they are, and the search then finds only the form that was typed.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from lawgraph.config.constants import COLLECTION_ARTICLES, COLLECTION_JUDGMENTS
from lawgraph.core.models import make_node_key
from lawgraph.db import ArangoStore
from lawgraph.db.queries import search as search_module
from lawgraph.db.queries.search import search_all

BW7 = "BWBR0005290"


def _put(store: ArangoStore, collection: str, key: str, **props: Any) -> None:
    doc = {"_key": key, "type": collection.rstrip("s"), "labels": [], "props": props}
    store.bulk_insert_or_update_nodes(collection, [doc])


@pytest.fixture()
def store(database: str) -> ArangoStore:
    search_module._law_cache.clear()
    store = ArangoStore()
    _put(
        store,
        COLLECTION_ARTICLES,
        make_node_key(BW7, "7:231"),
        bwb_id=BW7,
        article_number="7:231",
        display_name="Artikel 7:231",
        text="De rechter doet uitspraak over de vordering tot ontbinding van de huurovereenkomst.",
    )
    _put(
        store,
        COLLECTION_JUDGMENTS,
        "ecli_nl_hr_2021_1",
        ecli="ECLI:NL:HR:2021:1",
        display_name="ECLI:NL:HR:2021:1",
        summary="Ontslag op staande voet; de rechten van de werknemer uit de wetten.",
    )
    _wait_for_views(store, {"search_articles": 1, "search_judgments": 1})
    return store


def _wait_for_views(store: ArangoStore, sizes: dict[str, int]) -> None:
    """The search views fill asynchronously: wait until they hold what was written."""
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if all(
            next(iter(store.query(f"RETURN LENGTH(FOR d IN {view} RETURN 1)"))) >= size
            for view, size in sizes.items()
        ):
            return
        time.sleep(0.2)
    raise AssertionError(f"views not filled: {sizes}")


def _keys(store: ArangoStore, q: str, kind: str) -> list[str]:
    return [hit["key"] for hit in search_all(store, q=q, types=[kind])[kind]]


@pytest.mark.parametrize(
    "q", ["uitspraken", "vorderingen", "huurovereenkomsten", "uitspraak vorderingen"]
)
def test_an_article_is_found_by_another_form_of_its_words(
    store: ArangoStore, q: str
) -> None:
    assert _keys(store, q, "articles") == [make_node_key(BW7, "7:231")]


@pytest.mark.parametrize("q", ["ontslagen", "recht", "wet"])
def test_a_judgment_is_found_by_another_form_of_the_words_of_its_summary(
    store: ArangoStore, q: str
) -> None:
    assert _keys(store, q, "judgments") == ["ecli_nl_hr_2021_1"]


def test_a_word_that_is_not_there_finds_nothing(store: ArangoStore) -> None:
    assert _keys(store, "belastingen", "articles") == []
