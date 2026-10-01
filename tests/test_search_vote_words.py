"""The words that name the type of a vote, left out when votes are searched (BE-46): one
named set, kept small on purpose."""

from __future__ import annotations

from lawgraph.db.queries.search import _VOTE_WORDS


def test_the_vote_words_are_these_and_no_more() -> None:
    # "motie" is not one: it is a kind of vote, and narrows "motie abortus" to motions
    assert frozenset({"stemming", "stemmingen", "besluit", "besluiten"}) == _VOTE_WORDS
