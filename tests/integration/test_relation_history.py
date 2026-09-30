"""The history of an article, the laws that amended a law and the dossiers of a law, run
for real on a small hand-written graph.

``get_article_history`` finds the versions of an article by its ``stam_id`` (by its number
when it has none) and the titles of the dossiers their publications name;
``get_instrument_amended_by`` groups the AMENDS / INTRODUCES / REPEALS edges per amending
publication; ``get_instrument_dossiers`` says through what a dossier is linked to the law.
"""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.config.constants import (
    COLLECTION_ARTICLE_VERSIONS,
    COLLECTION_ARTICLES,
    COLLECTION_DOSSIERS,
    COLLECTION_INSTRUMENTS,
    RELATION_AMENDS,
    RELATION_INTRODUCES,
    RELATION_LEGISLATED_IN,
    RELATION_REPEALS,
)
from lawgraph.core.models import make_node_key
from lawgraph.db import ArangoStore
from lawgraph.db.edges import make_edge_doc
from lawgraph.db.queries.articles import get_article_history
from lawgraph.db.queries.instruments import (
    get_instrument_amended_by,
    get_instrument_dossiers,
)

LAW = "BWBR0009100"
OTHER_LAW = "BWBR0009200"
INSTRUMENT = f"{COLLECTION_INSTRUMENTS}/{make_node_key(LAW)}"
NEWER, OLDER, ELSEWHERE = "stb-2019-33", "stb-2018-5", "stb-2017-1"


def _put(store: ArangoStore, collection: str, key: str, **props: Any) -> None:
    doc = {"_key": key, "type": collection.rstrip("s"), "labels": [], "props": props}
    store.bulk_insert_or_update_nodes(collection, [doc])


def _article(store: ArangoStore, law: str, number: str, **props: Any) -> str:
    key = make_node_key(law, number)
    _put(store, COLLECTION_ARTICLES, key, bwb_id=law, article_number=number, **props)
    return f"{COLLECTION_ARTICLES}/{key}"


def _version(
    store: ArangoStore, key: str, number: str, valid_from: str, **props: Any
) -> None:
    _put(
        store,
        COLLECTION_ARTICLE_VERSIONS,
        key,
        bwb_id=LAW,
        article_number=number,
        valid_from=valid_from,
        **props,
    )


def _edge(from_id: str, to_id: str, relation: str, **meta: Any) -> dict[str, Any]:
    return make_edge_doc(from_id, to_id, relation, source="test", meta=meta)


@pytest.fixture()
def store(database: str) -> ArangoStore:
    """A law with an article that has a ``stam_id``, one without, and one without
    versions; two publications that change its articles and one that changes another
    law; dossiers linked to the law directly and through the publications."""
    store = ArangoStore()
    _put(store, COLLECTION_INSTRUMENTS, make_node_key(LAW), bwb_id=LAW)
    art_287 = _article(store, LAW, "287", stam_id="stam-1")
    art_300 = _article(store, LAW, "300")
    _article(store, LAW, "400")
    art_other = _article(store, OTHER_LAW, "1")

    # the article was numbered 286 at first; a version of another stam has its number now
    _version(
        store,
        "v1",
        "287",
        "2001-01-01",
        stam_id="stam-1",
        origin_publication={"dossiers": ["12345"]},  # a dossier nobody loaded
    )
    _version(
        store,
        "v0",
        "286",
        "2000-01-01",
        stam_id="stam-1",
        origin_publication={"dossiers": ["35786"]},
    )
    _version(store, "v_other", "287", "2002-01-01", stam_id="stam-2")
    _version(store, "v300", "300", "2003-01-01")

    for number, title, opened in (
        ("35786", "Wijziging Burgerlijk Wetboek", "2020-01-01"),
        ("111", "Dossier 111", "2020-01-01"),
        ("222", "Dossier 222", "2019-01-01"),
        ("444", "Dossier 444", "2021-01-01"),
    ):
        _put(
            store,
            COLLECTION_DOSSIERS,
            number,
            number=number,
            label=number,
            title=title,
            opened_on=opened,
        )

    _put(
        store,
        COLLECTION_INSTRUMENTS,
        NEWER,
        date_published="2019-06-01",
        date_signed="2019-05-01",
        dossier_numbers=["35786"],
    )
    _put(
        store,
        COLLECTION_INSTRUMENTS,
        OLDER,
        identifier=OLDER,
        date_published="2018-01-01",
        date_signed="2017-12-01",
    )
    _put(store, COLLECTION_INSTRUMENTS, ELSEWHERE, date_published="2020-01-01")

    newer = f"{COLLECTION_INSTRUMENTS}/{NEWER}"
    older = f"{COLLECTION_INSTRUMENTS}/{OLDER}"
    elsewhere = f"{COLLECTION_INSTRUMENTS}/{ELSEWHERE}"
    dossier = f"{COLLECTION_DOSSIERS}/"
    store.bulk_insert_or_update_edges(
        [
            _edge(newer, art_287, RELATION_AMENDS, effective_date="2019-07-01"),
            _edge(newer, art_300, RELATION_INTRODUCES, effective_date="2019-08-01"),
            _edge(older, art_287, RELATION_REPEALS, effective_date="2018-02-01"),
            _edge(older, art_300, RELATION_AMENDS, effective_date="2018-03-01"),
            _edge(elsewhere, art_other, RELATION_AMENDS),
            # 111 through the law and a publication, 222 through both publications
            _edge(INSTRUMENT, f"{dossier}111", RELATION_LEGISLATED_IN),
            _edge(newer, f"{dossier}111", RELATION_LEGISLATED_IN),
            _edge(newer, f"{dossier}222", RELATION_LEGISLATED_IN),
            _edge(older, f"{dossier}222", RELATION_LEGISLATED_IN),
            _edge(elsewhere, f"{dossier}444", RELATION_LEGISLATED_IN),
        ]
    )
    return store


# ── get_article_history ─────────────────────────────────────────────────────


def test_the_history_follows_the_stam_id_oldest_first_with_dossier_titles(
    store: ArangoStore,
) -> None:
    data = get_article_history(store, LAW, "287")

    assert data.article["_key"] == make_node_key(LAW, "287")
    assert [v["_key"] for v in data.versions] == ["v0", "v1"]
    # the dossier nobody loaded has no title
    assert data.dossier_titles == {"35786": "Wijziging Burgerlijk Wetboek"}


def test_an_article_without_stam_id_is_followed_by_its_number(
    store: ArangoStore,
) -> None:
    assert [v["_key"] for v in get_article_history(store, LAW, "300").versions] == [
        "v300"
    ]


def test_an_article_without_versions_has_no_history_and_no_dossiers(
    store: ArangoStore,
) -> None:
    data = get_article_history(store, LAW, "400")
    assert data.versions == [] and data.dossier_titles == {}


def test_the_history_of_an_unknown_article_is_an_error(store: ArangoStore) -> None:
    with pytest.raises(ValueError):
        get_article_history(store, LAW, "999")


# ── get_instrument_amended_by ───────────────────────────────────────────────


def test_the_amending_publications_are_counted_per_relation_newest_first(
    store: ArangoStore,
) -> None:
    data = get_instrument_amended_by(store, LAW)

    assert data.total == 2  # the publication that changes another law is not one
    rows = [
        (
            row["instrument"]["_key"],
            row["amends"],
            row["introduces"],
            row["repeals"],
            row["articles_affected"],
            row["first_effective_date"],
        )
        for row in data.items
    ]
    assert rows == [
        (NEWER, 1, 1, 0, 2, "2019-07-01"),
        (OLDER, 1, 0, 1, 2, "2018-02-01"),
    ]
    assert data.dossier_titles == {"35786": "Wijziging Burgerlijk Wetboek"}


def test_the_amending_publications_are_paged_with_the_whole_total(
    store: ArangoStore,
) -> None:
    page = get_instrument_amended_by(store, LAW, limit=1, offset=1)
    assert page.total == 2
    assert [row["instrument"]["_key"] for row in page.items] == [OLDER]
    assert page.dossier_titles == {}  # the older publication names no dossier

    nothing = get_instrument_amended_by(store, "BWBR0009300")  # no articles
    assert (nothing.total, nothing.items, nothing.dossier_titles) == (0, [], {})


# ── get_instrument_dossiers ─────────────────────────────────────────────────


def test_a_dossier_says_whether_the_law_or_a_publication_links_it(
    store: ArangoStore,
) -> None:
    rows, total = get_instrument_dossiers(store, LAW)

    assert total == 2  # not the dossier of the publication that changes another law
    assert [
        (row["dossier"]["_key"], row["via"], row["publication"]) for row in rows
    ] == [
        # linked both ways: the law's own link wins
        ("111", "instrument", None),
        # the newest publication, by its key when it has no identifier
        ("222", "amending_publication", NEWER),
    ]
    page, total = get_instrument_dossiers(store, LAW, limit=1)
    assert total == 2 and [row["dossier"]["_key"] for row in page] == ["111"]


# ── one query per step, not one per row ─────────────────────────────────────


def _count_queries(store: ArangoStore, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The queries *store* runs from here on."""
    calls: list[str] = []
    run = store.query

    def counted(query: str, *args: Any, **kwargs: Any) -> Any:
        calls.append(query)
        return run(query, *args, **kwargs)

    monkeypatch.setattr(store, "query", counted)
    return calls


def test_the_dossier_titles_are_looked_up_at_once(
    store: ArangoStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two rows that each name a dossier: a lookup per row would be a third query."""
    calls = _count_queries(store, monkeypatch)
    assert len(get_article_history(store, LAW, "287").versions) == 2
    assert len(calls) == 2  # the versions, then every dossier title at once

    calls.clear()
    assert len(get_instrument_amended_by(store, LAW).items) == 2
    assert len(calls) == 2  # the counts per publication, then the titles at once

    calls.clear()
    assert get_instrument_dossiers(store, LAW)[1] == 2
    assert len(calls) == 1


def test_a_history_that_names_no_dossier_skips_the_title_lookup(
    store: ArangoStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _count_queries(store, monkeypatch)
    get_article_history(store, LAW, "400")
    assert len(calls) == 1
