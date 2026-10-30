"""The score of a hit that matched on words only: by its rank in the database, between
``SCORE_WORDS`` and ``SCORE_CONTAINS``, in the order of the database (B68: every such hit
scored 0.1)."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.db.queries.search.ranking import (
    SCORE_CONTAINS,
    SCORE_TITLE,
    SCORE_WORDS,
    WORDS_SPAN,
    rank_hits,
    words_score,
)


def _hit(n: int, rank: float | None, **extra: Any) -> dict[str, Any]:
    return {
        "id": f"articles/x_{n}",
        "key": f"x_{n}",
        "collection": "articles",
        "display_name": f"Art. {n} Wet",
        "extra": {"article_number": str(n), **extra},
        "rank": rank,
    }


def test_the_score_rises_with_the_rank() -> None:
    assert words_score({"rank": 0.0}) == SCORE_WORDS
    assert words_score({"rank": 10.0}) == pytest.approx(SCORE_WORDS + WORDS_SPAN / 2)
    assert SCORE_WORDS < words_score({"rank": 3.0}) < words_score({"rank": 30.0})
    assert words_score({"rank": 1e6}) < SCORE_CONTAINS
    # a better tier in the database (no rank of its own): the top of the span
    assert words_score({"rank": None}) == pytest.approx(SCORE_WORDS + WORDS_SPAN)
    # no rank at all (while typing, a precise lookup): as before
    assert words_score({}) == SCORE_WORDS


def test_the_hits_keep_the_order_of_the_database_without_their_rank() -> None:
    hits = [_hit(1, None), _hit(2, 31.5), _hit(3, 31.5), _hit(4, 12.0), _hit(5, 0.4)]
    ranked = rank_hits("gewichtige belangen", hits, today="2026-10-30")
    assert [h["key"] for h in ranked] == ["x_1", "x_2", "x_3", "x_4", "x_5"]
    scores = [h["score"] for h in ranked]
    assert scores == sorted(scores, reverse=True)
    assert scores[1] == scores[2] > scores[3] > scores[4] > SCORE_WORDS
    assert [h["key"] for h in ranked if "rank" in h] == []


def test_a_score_of_a_better_tier_or_given_stands() -> None:
    named = {**_hit(1, 2.0), "score": SCORE_TITLE}
    heading = _hit(2, 2.0, heading="Over gewichtige belangen van de staat")
    ranked = rank_hits("gewichtige belangen", [_hit(3, 50.0), named, heading])
    assert [(h["key"], h["score"]) for h in ranked][:2] == [
        ("x_1", SCORE_TITLE),
        ("x_2", SCORE_CONTAINS),
    ]
