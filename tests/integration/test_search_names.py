"""Headings, division titles and aliases in the search, run for real on the small test server.

An article is found by the title of its kop and by the titles of the divisions it stands in;
a law by every name it is cited by (``BW``, ``Boek 6 BW``, ``6 BW``, ``BW6``). A hit whose
heading or alias is the whole query ranks above one that only holds its words.
"""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
)
from lawgraph.core.bwb_wti import instrument_aliases
from lawgraph.core.models import make_node_key
from lawgraph.db import ArangoStore
from lawgraph.db.queries import normalize as normalize_queries
from lawgraph.db.queries.search import (
    SCORE_CONTAINS,
    SCORE_IDENTIFIER,
    SCORE_TITLE,
    SCORE_WORDS,
    search_all,
)
from lawgraph.db.schema import _VIEW_SPECS, _indexed_fields, _nested_fields
from tests.integration.seed import wait_for_views

SR = "BWBR0001854"
UAVG = "BWBR0040940"
BW1 = "BWBR0002656"
BW6 = "BWBR0005289"


def _put(store: ArangoStore, collection: str, key: str, **props: Any) -> None:
    doc = {"_key": key, "type": collection.rstrip("s"), "labels": [], "props": props}
    store.bulk_insert_or_update_nodes(collection, [doc])


def _put_articles(store: ArangoStore) -> None:
    _put(
        store,
        COLLECTION_ARTICLES,
        make_node_key(UAVG, "1"),
        bwb_id=UAVG,
        article_number="1",
        label="Artikel 1",
        heading="Definities",
        display_name="Artikel 1 Uitvoeringswet AVG",
        text="In deze wet en de daarop berustende bepalingen wordt verstaan onder: ...",
        breadcrumb=[{"type": "hoofdstuk", "label": "Hoofdstuk 1", "title": "Algemeen"}],
    )
    _put(
        store,
        COLLECTION_ARTICLES,
        make_node_key(SR, "41"),
        bwb_id=SR,
        article_number="41",
        label="Artikel 41",
        display_name="Artikel 41 Wetboek van Strafrecht",
        text="Niet strafbaar is hij die een feit begaat, geboden door de noodzakelijke "
        "verdediging van eigen of eens anders lijf, eerbaarheid of goed.",
        breadcrumb=[
            {"type": "boek", "label": "Eerste Boek", "title": "Algemene bepalingen"},
            {
                "type": "titeldeel",
                "label": "Titel III",
                "title": "Uitsluiting en verhoging van strafbaarheid",
            },
        ],
    )


def _put_instruments(store: ArangoStore) -> None:
    for bwb_id, title in (
        (SR, "Wetboek van Strafrecht"),
        (BW1, "Burgerlijk Wetboek Boek 1"),
        (BW6, "Burgerlijk Wetboek Boek 6"),
    ):
        _put(
            store,
            COLLECTION_INSTRUMENTS,
            make_node_key(bwb_id),
            bwb_id=bwb_id,
            title=title,
            citation_title=title,
            display_name=title,
        )
    # the short titles and aliases as ``normalize bwb`` writes them from the WTI records
    aliases = instrument_aliases(
        {
            SR: ["Sr", "WvS", "WvSr"],
            BW1: ["BW", "BW Boek 1", "BW1"],
            BW6: ["BW", "BW Boek 6", "BW6"],
        }
    )
    rows = [
        {"key": make_node_key(b), "short_title": s, "aliases": aliases[b]}
        for b, s in ((SR, "Sr"), (BW1, "BW1"), (BW6, "BW6"))
    ]
    assert normalize_queries.update_abbreviations(store, rows) == 3
    assert normalize_queries.update_abbreviations(store, rows) == 0  # nothing changed


@pytest.fixture()
def store(database: str) -> ArangoStore:
    store = ArangoStore()
    _put_articles(store)
    _put(
        store,
        COLLECTION_JUDGMENTS,
        "ecli_nl_hr_2021_2",
        ecli="ECLI:NL:HR:2021:2",
        display_name="ECLI:NL:HR:2021:2",
        summary="De definities van de wet en de uitsluiting van aansprakelijkheid.",
    )
    _put_instruments(store)
    wait_for_views(
        store, {"search_articles": 2, "search_judgments": 1, "search_instruments": 3}
    )
    return store


def _hits(store: ArangoStore, q: str, kind: str) -> list[tuple[str, float]]:
    return [(h["key"], h["score"]) for h in search_all(store, q=q, types=[kind])[kind]]


def test_an_article_is_found_by_its_heading_and_ranks_above_a_judgment(
    store: ArangoStore,
) -> None:
    results = search_all(store, q="definities", types=["articles", "judgments"])
    assert [(h["key"], h["score"]) for h in results["articles"]] == [
        (make_node_key(UAVG, "1"), SCORE_TITLE)
    ]
    assert results["articles"][0]["extra"]["heading"] == "Definities"
    assert [(h["key"], h["score"]) for h in results["judgments"]] == [
        ("ecli_nl_hr_2021_2", SCORE_WORDS)
    ]


def test_an_article_is_found_by_the_title_of_its_division(store: ArangoStore) -> None:
    hits = search_all(store, q="uitsluiting strafbaarheid", types=["articles"])
    assert [(h["key"], h["score"]) for h in hits["articles"]] == [
        (make_node_key(SR, "41"), SCORE_CONTAINS)
    ]
    assert hits["articles"][0]["extra"]["division_titles"] == [
        "Algemene bepalingen",
        "Uitsluiting en verhoging van strafbaarheid",
    ]


def test_a_query_of_many_words_runs_on_every_view(store: ArangoStore) -> None:
    # the whole title of the division: five words over seven fields of the instruments
    q = "Uitsluiting en verhoging van strafbaarheid"
    results = search_all(store, q=q, types=["articles", "instruments", "judgments"])
    assert [h["key"] for h in results["articles"]] == [make_node_key(SR, "41")]
    assert results["instruments"] == results["judgments"] == []


def test_a_word_in_no_heading_title_or_text_finds_nothing(store: ArangoStore) -> None:
    # "noodweer" is the common name of art. 41 Sr, but the BWB prints it nowhere
    assert _hits(store, "noodweer", "articles") == []


def test_the_code_finds_every_book_and_no_other_law(store: ArangoStore) -> None:
    assert sorted(_hits(store, "BW", "instruments")) == [
        (make_node_key(BW1), SCORE_TITLE),
        (make_node_key(BW6), SCORE_TITLE),
    ]


@pytest.mark.parametrize("q", ["Boek 6 BW", "6 BW", "BW 6", "bw boek 6"])
def test_a_book_is_found_first_by_every_form_of_its_name(
    store: ArangoStore, q: str
) -> None:
    assert _hits(store, q, "instruments")[0] == (make_node_key(BW6), SCORE_TITLE)


def test_the_short_title_is_an_identifier_and_another_abbreviation_a_name(
    store: ArangoStore,
) -> None:
    assert _hits(store, "BW6", "instruments")[0] == (
        make_node_key(BW6),
        SCORE_IDENTIFIER,
    )
    assert _hits(store, "WvS", "instruments") == [(make_node_key(SR), SCORE_TITLE)]


def test_the_views_as_the_server_returns_them_match_their_definition(
    store: ArangoStore,
) -> None:
    # else every start would rebuild them: a nested field comes back nested
    for view in ("search_articles", "search_instruments"):
        links = store.db.view(view)["links"]
        wanted = {
            collection: {"fields": {"props": {"fields": _nested_fields(fields)}}}
            for collection, fields in _VIEW_SPECS[view].items()
        }
        assert _indexed_fields(links) == _indexed_fields(wanted)
