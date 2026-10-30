"""The words of a query: a phrase in quotes is one token, and the runs of its words in
order that rank a hit higher."""

from __future__ import annotations

import pytest

from lawgraph.core.word_forms import word_forms
from lawgraph.db.queries.search.clause import (
    Order,
    is_phrase,
    tokenize_search_query,
    word_order,
)


@pytest.mark.parametrize(
    ("q", "tokens"),
    [
        (
            '"Andere gewichtige  belangen van de Staat"',
            ["andere gewichtige belangen van de staat"],
        ),
        ('"te beschermen belangen" Wiv', ["te beschermen belangen", "wiv"]),
        ("„belang van de staat” sr", ["belang van de staat", "sr"]),
        # one word in quotes is a word; an open quote runs to the end
        ('"verjaring" "van de vordering', ["verjaring", "van de vordering"]),
        ("ECLI:NL:HR:2016:168", ["ecli:nl:hr:2016:168"]),
        ('a "b" huur', ["huur"]),
    ],
)
def test_a_phrase_in_quotes_is_one_token(q: str, tokens: list[str]) -> None:
    assert tokenize_search_query(q) == tokens


def test_a_phrase_is_a_token_of_words() -> None:
    assert is_phrase("belangen van de staat")
    assert not is_phrase("belangen")
    # its words are no forms of one another: no plural of its last one
    assert word_forms("kosten van het proces") == "kosten van het proces"
    assert word_forms("proces") == "proces procezen"


def test_the_runs_of_words_in_order_hold_the_stop_words_between_them() -> None:
    stop = {"van", "de", "te", "het"}
    assert word_order(["gewichtige", "belangen", "van", "de", "staat"], stop) == Order(
        ("gewichtige belangen", "belangen van de staat"),
        "gewichtige belangen van de staat",
    )
    # stop words at the ends are no part of a run; two words are one pair, no whole
    assert word_order(["te", "beschermen", "belangen", "van"], stop) == Order(
        ("beschermen belangen",)
    )
    assert word_order(["de", "huur"], stop) == Order()
    assert word_order(["van", "de"], stop) == Order()
