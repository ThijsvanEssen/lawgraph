"""Each type ``/api/search`` searches is one ``SearchType``: one searched by the words of its
fields has them in ``SEARCH_FIELDS`` and an order while typing; one whose hits of a word are
kept ranks a common word by its candidates."""

from __future__ import annotations

from lawgraph.db.queries.search.candidates import CANDIDATE_TYPES
from lawgraph.db.queries.search.searched import FIELD_SEARCHED, SEARCHED
from lawgraph.db.queries.search.types import SEARCHES
from lawgraph.db.schema import SEARCH_FIELDS, SEARCH_WORDS
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


def test_what_a_type_is_searched_in_comes_from_its_fields() -> None:
    """``searched`` of a type: the words of the fields its search reads, and its text
    ``none`` when it has one the search does not read (a judgment, a paper)."""
    assert SEARCHED["judgments"] == {
        "fields": ["title", "name", "number", "summary"],
        "completeness": {"text": {"state": "none"}},
    }
    assert SEARCHED["documents"] == {
        "fields": ["title", "number"],
        "completeness": {"text": {"state": "none"}},
    }
    assert SEARCHED["articles"]["completeness"] == {"text": {"state": "done"}}
    assert "text" in SEARCHED["commitments"]["fields"]
    assert SEARCHED["dossiers"] == {"fields": ["title", "number"], "completeness": {}}
    assert SEARCHED["members"]["fields"] == ["name"]
    assert SEARCHED["decisions"]["fields"] == ["title", "kind"]
    assert set(SEARCHED) == set(SEARCHES)


def test_every_searched_field_has_a_word() -> None:
    fields = {f for table in SEARCH_FIELDS.values() for f in table}
    fields |= {f for words in SEARCH_WORDS.values() for f in words}
    assert fields <= set(FIELD_SEARCHED), sorted(fields - set(FIELD_SEARCHED))
