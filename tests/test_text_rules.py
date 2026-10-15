"""The rules of text the explorer applies as well, against ``tests/data/text-rules.json``
(the same file is in lawgraph-explorer): the length of a word matched whole, a long date,
the anchors of the divisions of a breadcrumb (each crumb of an answer has its own) and
the length of a neighbor's summary. The words themselves are matched by the database:
``tests/pg/test_text_rules.py``."""

from __future__ import annotations

import json
from typing import Any

import pytest

from lawgraph.api.schemas.instruments import breadcrumb_dtos
from lawgraph.core.division_anchor import division_anchors
from lawgraph.core.dutch_dates import long_date
from lawgraph.db._rows import NEIGHBOR_SUMMARY_CHARS, light_node_doc
from lawgraph.db.queries import _words
from tests.paths import TESTS

RULES: dict[str, Any] = json.loads((TESTS / "data" / "text-rules.json").read_text())


def test_a_short_word_is_matched_whole() -> None:
    limit = RULES["whole_word_max"]
    assert _words.WHOLE_WORD_MAX == limit
    assert _words.whole("a" * limit) and not _words.whole("a" * (limit + 1))


@pytest.mark.parametrize("case", RULES["long_dates"], ids=lambda c: str(c["iso"]))
def test_a_long_date(case: dict[str, Any]) -> None:
    assert long_date(case["iso"]) == case["text"]


@pytest.mark.parametrize(
    "case", RULES["division_anchors"], ids=lambda c: c["anchors"][-1]
)
def test_the_anchors_of_a_breadcrumb(case: dict[str, Any]) -> None:
    """Each crumb of an answer carries its anchor (``breadcrumb_dtos``)."""
    assert division_anchors(case["breadcrumb"]) == case["anchors"]
    crumbs = breadcrumb_dtos(case["breadcrumb"])
    assert [crumb.anchor for crumb in crumbs] == case["anchors"]


def test_a_summary_is_cut_where_the_explorer_expects_it() -> None:
    chars = RULES["summary_chars"]
    assert NEIGHBOR_SUMMARY_CHARS == chars
    row = {"id": "judgments/x", "key": "x", "type": "judgment", "labels": []}
    long = light_node_doc(row | {"props": {"summary": "a" * (chars + 1)}})
    assert long["props"]["summary"] == "a" * chars + "…"
    exact = light_node_doc(row | {"props": {"summary": "a" * chars}})
    assert exact["props"]["summary"] == "a" * chars
