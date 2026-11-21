"""The full search ranks the work of the last 12 months higher within a type, never above
what the query names; ``sort=newest`` orders the hits of a type with a date newest first."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from lawgraph.core.time import dutch_today
from lawgraph.db import GraphStore, version_cache
from tests.databases import Api

# a day of this year, and one long ago
RECENT = (dutch_today() - dt.timedelta(days=30)).isoformat()
LAST_MONTHS = (dutch_today() - dt.timedelta(days=200)).isoformat()
OLD = "2010-03-01"


def _nodes(store: GraphStore, collection: str, rows: list[dict[str, Any]]) -> None:
    store.bulk_insert_or_update_nodes(
        collection,
        [
            {"key": r.pop("key"), "type": r.pop("type"), "labels": [], "props": r}
            for r in rows
        ],
    )


@pytest.fixture()
def store(store: GraphStore) -> GraphStore:
    version_cache.clear()
    # papers with "gevangenis" in their title, the old one shorter (BM25 ranks it higher by
    # its words alone); others for the counts of the words
    _nodes(
        store,
        "documents",
        [
            {"key": "old", "type": "document", "title": "Brief over de gevangenis",
             "date": f"{OLD}T10:00:00"},
            {"key": "recent", "type": "document",
             "title": "Brief over de nieuwe gevangenis", "date": f"{RECENT}T10:00:00"},
            *({"key": f"other_{n}", "type": "document", "title": f"Brief over de huur {n}",
               "date": "2015-01-01"} for n in range(20)),
        ],
    )  # fmt: skip
    # a judgment named Urgenda, long ago, and two that hold the name in their summary
    _nodes(
        store,
        "judgments",
        [
            {"key": "urgenda", "type": "judgment", "ecli": "ECLI:NL:HR:2019:2006",
             "names": ["Urgenda"], "display_name": "Hoge Raad 2019-12-20 / 19/00135",
             "summary": "Klimaat.", "date_eff": "2019-12-20"},
            {"key": "after", "type": "judgment", "ecli": "ECLI:NL:RBDHA:2024:1",
             "display_name": "Rechtbank Den Haag 2024-01-01 / 1",
             "summary": "Na Urgenda.", "date_eff": LAST_MONTHS},
            {"key": "later", "type": "judgment", "ecli": "ECLI:NL:RBDHA:2024:2",
             "display_name": "Rechtbank Den Haag 2024-02-01 / 2",
             "summary": "Weer Urgenda.", "date_eff": RECENT},
            {"key": "before", "type": "judgment", "ecli": "ECLI:NL:RBDHA:2015:3",
             "display_name": "Rechtbank Den Haag 2015-06-24 / 3",
             "summary": "Urgenda in eerste aanleg.", "date_eff": "2015-06-24"},
        ],
    )  # fmt: skip
    # a law whose citation title is the query, long in force, and a new one that holds it
    _nodes(
        store,
        "instruments",
        [
            {"key": "bwbr0009709", "type": "instrument", "bwb_id": "BWBR0009709",
             "title": "Penitentiaire beginselenwet",
             "citation_title": "Penitentiaire beginselenwet", "date_in_force": "1999-01-01"},
            {"key": "bwbr0099999", "type": "instrument", "bwb_id": "BWBR0099999",
             "title": "Wet tot wijziging van de Penitentiaire beginselenwet",
             "date_in_force": RECENT},
        ],
    )  # fmt: skip
    # an article of the old law its case law calls "noodweer" (a term), and one of the new
    # law whose shorter text holds the word
    _nodes(
        store,
        "articles",
        [
            {"key": "bwbr0009709_41", "type": "article", "bwb_id": "BWBR0009709",
             "article_number": "41", "display_name": "Artikel 41 Penitentiaire beginselenwet",
             "text": "Niet strafbaar is hij die een feit begaat, geboden door de "
                     "noodzakelijke verdediging van eigen of eens anders lijf (noodweer)."},
            {"key": "bwbr0099999_1", "type": "article", "bwb_id": "BWBR0099999",
             "article_number": "1", "display_name": "Artikel 1 Wijzigingswet",
             "text": "Noodweer in de inrichting."},
            *({"key": f"bwbr0099999_{n}", "type": "article", "bwb_id": "BWBR0099999",
               "article_number": str(n), "display_name": f"Artikel {n} Wijzigingswet",
               "text": f"Een regel over de inrichting {n}."} for n in range(2, 20)),
        ],
    )  # fmt: skip
    store.execute(
        "INSERT INTO lg_article_terms (article_id, terms)"
        " VALUES ('articles/bwbr0009709_41', lg_tokens('noodweer'))"
    )
    for table in ("documents", "judgments", "instruments", "articles"):
        store.execute(f"ANALYZE {table}")
    return store


def _keys(answer: dict[str, Any], table: str) -> list[str]:
    return [hit["key"] for hit in answer["results"][table]]


def test_the_work_of_this_year_comes_first_of_hits_that_weigh_about_the_same(
    api: Api,
) -> None:
    answer = api.get_json("/api/search", q="gevangenis", types=["documents"])
    assert _keys(answer, "documents") == ["recent", "old"]


def test_what_the_query_names_stays_above_the_work_of_this_year(api: Api) -> None:
    """A law by its whole citation title, a judgment by its name: before a newer hit that
    holds the words, in either order."""
    for sort in ("relevance", "newest"):
        laws = api.get_json(
            "/api/search", q="Penitentiaire beginselenwet", types=["instruments"],
            sort=sort,
        )  # fmt: skip
        assert _keys(laws, "instruments") == ["bwbr0009709", "bwbr0099999"], sort
        judgments = api.get_json(
            "/api/search", q="Urgenda", types=["judgments"], sort=sort
        )
        assert _keys(judgments, "judgments")[0] == "urgenda", sort


def test_an_article_named_by_a_term_stays_above_one_of_a_new_law(api: Api) -> None:
    answer = api.get_json("/api/search", q="noodweer", types=["articles"])
    assert _keys(answer, "articles") == ["bwbr0009709_41", "bwbr0099999_1"]


def test_newest_first_orders_the_hits_of_a_type_by_their_date(api: Api) -> None:
    """The judgment the query names first, the others by the day of their decision, the
    newest first, unranked by their words."""
    answer = api.get_json(
        "/api/search", q="Urgenda", types=["judgments", "members"], sort="newest"
    )
    assert _keys(answer, "judgments") == ["urgenda", "later", "after", "before"]
    words_only = [h["score"] for h in answer["results"]["judgments"][1:]]
    assert words_only == [0.1, 0.1, 0.1]
    papers = api.get_json(
        "/api/search", q="brief", types=["documents"], sort="newest", limit=3
    )
    assert _keys(papers, "documents")[:2] == ["recent", "other_0"]


def test_newest_first_is_of_the_full_search_only(api: Api) -> None:
    response = api.get(
        "/api/search", params={"q": "urgenda", "mode": "live", "sort": "newest"}
    )
    assert response.status_code == 422, response.text
    response = api.get("/api/search", params={"q": "urgenda", "sort": "oldest"})
    assert response.status_code == 422, response.text
