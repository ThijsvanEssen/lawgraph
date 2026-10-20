"""Each type ``/api/search`` searches is one ``SearchType``: one searched by the words of its
fields has them in ``SEARCH_FIELDS`` and an order while typing; one whose hits of a word are
kept ranks a common word by its candidates."""

from __future__ import annotations

from lawgraph.db.queries.search.candidates import CANDIDATE_TYPES
from lawgraph.db.queries.search.types import SEARCHES
from lawgraph.db.schema import SEARCH_FIELDS
from tests.asserts import show_items


def test_a_type_searched_by_its_words_has_them_indexed() -> None:
    for table, kind in SEARCHES.items():
        assert kind.table == table
        if kind.fields:
            assert set(kind.fields) <= set(SEARCH_FIELDS[table]), table
            assert set(kind.boosts) <= set(kind.fields), table
            assert kind.live_order, table


def test_the_kept_types_are_those_that_rank_their_candidates() -> None:
    assert [kind.table for kind in CANDIDATE_TYPES] == [
        "articles",
        "judgments",
        "documents",
    ]
    failing = [kind for kind in CANDIDATE_TYPES if not kind.fields]
    assert not failing, show_items(failing)
