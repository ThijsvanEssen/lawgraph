"""``retrieve staatscourant-posts`` asks the Staatscourant about every post whose function
names no ministry, once for a post that ended and on every run for one still held."""

from __future__ import annotations

from collections import Counter

from lawgraph.config.constants import (
    RAW_KIND_STCRT_POST_CREATORS,
    SOURCE_STAATSCOURANT,
)
from lawgraph.db import GraphStore
from lawgraph.db.queries import raw as raw_queries
from lawgraph.pipelines.retrieve.staatscourant_posts import (
    StaatscourantPostsRetrievePipeline,
)

from .test_government_functions import page, store_pages


class _Client:
    def __init__(self) -> None:
        self.asked: list[tuple[str, str, str]] = []

    def creators(self, phrase: str, date_from: str, date_to: str) -> Counter[str]:
        self.asked.append((phrase, date_from, date_to))
        return Counter({"Ministerie van Buitenlandse Zaken": 20})


def test_ended_posts_are_asked_once_and_held_ones_every_run(database: str) -> None:
    store = GraphStore()
    store_pages(
        store,
        {
            # before 1995: not in the repository
            "kabinet-lubbers-i": page(
                "Lubbers I",
                "4 november 1982",
                ("Minister voor Ontwikkelingssamenwerking", ["drs. E.M. Schoo (VVD)"]),
            ),
            "kabinet-lubbers-ii": page(
                "Lubbers II",
                "14 juli 1986",
                ("Minister van Financiën", ["dr. H.O.C.R. Ruding (CDA)"]),
            ),
            "kabinet-rutte-ii": page(
                "Rutte II",
                "5 november 2012",
                (
                    "Minister voor Buitenlandse Handel en Ontwikkelingssamenwerking",
                    ["Drs. E.M.J. Ploumen (PvdA)"],
                ),
                ("Minister van Financiën", ["J.R.V.A. Dijsselbloem (PvdA)"]),
            ),
            "kabinet-schoof": page(
                "Schoof",
                "2 juli 2024",
                (
                    "Minister voor Buitenlandse Handel en Ontwikkelingshulp",
                    ["Drs. R.J. Klever (PVV)"],
                ),
            ),
        },
    )
    first = _Client()
    result = StaatscourantPostsRetrievePipeline(store, client=first).run()  # type: ignore[arg-type]
    assert not result.errors, result.errors
    assert sorted((phrase, date_from) for phrase, date_from, _ in first.asked) == [
        ("minister voor buitenlandse handel en ontwikkelingshulp", "2024-07-02"),
        (
            "minister voor buitenlandse handel en ontwikkelingssamenwerking",
            "2012-11-05",
        ),
    ]
    stored = {
        row["id"]
        for row in raw_queries.fetch_times(
            store, source=SOURCE_STAATSCOURANT, kind=RAW_KIND_STCRT_POST_CREATORS
        )
    }
    assert stored == {
        "minister voor buitenlandse handel en ontwikkelingssamenwerking|2012-11-05|2024-07-02",
        "minister voor buitenlandse handel en ontwikkelingshulp|2024-07-02|",
    }

    again = _Client()
    StaatscourantPostsRetrievePipeline(store, client=again).run()  # type: ignore[arg-type]
    assert [phrase for phrase, _, _ in again.asked] == [
        "minister voor buitenlandse handel en ontwikkelingshulp"
    ]
