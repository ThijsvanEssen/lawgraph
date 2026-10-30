"""The description of an article's page: the start of its text, then what the page has
besides, within what a search result shows."""

from __future__ import annotations

import pytest

from lawgraph.api.seo.pages.base import DESCRIPTION_MAX
from lawgraph.api.seo.pages.laws import _article_description

TEXT = (
    "Onder bestuursorgaan wordt verstaan: a. een orgaan van een rechtspersoon die "
    "krachtens publiekrecht is ingesteld, of b. een ander persoon of college, met enig "
    "openbaar gezag bekleed."
)


def test_the_text_and_all_it_has() -> None:
    got = _article_description(TEXT, {"judgments": 312, "references": 45}, True)
    assert got.startswith("Onder bestuursorgaan wordt verstaan: a. een orgaan")
    assert got.endswith("… Met 312 uitspraken, wetsgeschiedenis en 45 verwijzingen.")
    assert len(got) <= DESCRIPTION_MAX
    assert "·" not in got


@pytest.mark.parametrize(
    ("counts", "explained", "tail"),
    [
        ({"judgments": 1, "references": 0}, False, "Met 1 uitspraak."),
        (
            {"judgments": 0, "references": 1},
            True,
            "Met wetsgeschiedenis en 1 verwijzing.",
        ),
        (
            {"judgments": 1194, "references": 2},
            False,
            "Met 1.194 uitspraken en 2 verwijzingen.",
        ),
    ],
)
def test_only_what_there_is(counts: dict[str, int], explained: bool, tail: str) -> None:
    got = _article_description(TEXT, counts, explained)
    assert got.endswith(" " + tail)
    assert " 0 " not in got
    assert len(got) <= DESCRIPTION_MAX


def test_nothing_besides_is_the_text_alone() -> None:
    assert _article_description("Kort artikel.", {}, False) == "Kort artikel."
    got = _article_description(TEXT, {"judgments": 0, "references": 0}, False)
    assert got == TEXT[: len(got) - 1].rstrip() + "…"
    assert "Met" not in got


def test_a_short_text_is_whole() -> None:
    got = _article_description("Kort artikel.", {"judgments": 3}, False)
    assert got == "Kort artikel. Met 3 uitspraken."
