"""The Convention articles an ECHR judgment applies, as HUDOC names them.

The pipeline itself runs against the test server: ``tests/integration/test_echr_convention.py``.
"""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.db.queries.semantic import rechtspraak as semantic_rechtspraak
from lawgraph.pipelines.semantic.echr import (
    ECHRSemanticPipeline,
    convention_articles,
    protocol_articles,
    protocol_treaties,
)


@pytest.mark.parametrize(
    ("labels", "expected"),
    [
        (["8;8-1;8-2;41"], {"8": ["1", "2"], "41": []}),
        (["5;5-1;5-1-f;41"], {"5": ["1"], "41": []}),
        # articles applied together, and one paragraph named twice
        (["8;8-1;8-2;13;13+8-1"], {"8": ["1", "2"], "13": []}),
        (["6;6+6-3-c;6-1;6-3"], {"6": ["3", "1"]}),
        # an article of a Protocol is of a treaty of its own
        (["P1-1;P1-1-1;14"], {"14": []}),
        ("3", {"3": []}),
        ([], {}),
        (None, {}),
    ],
)
def test_the_articles_and_their_paragraphs(
    labels: Any, expected: dict[str, list[str]]
) -> None:
    assert convention_articles(labels) == expected


def test_without_judgments_nothing_is_written(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(semantic_rechtspraak, "echr_judgments", lambda store: iter([]))

    assert ECHRSemanticPipeline(store=object()).run().created == 0


@pytest.mark.parametrize(
    ("labels", "expected"),
    [
        (["8;P1-1;P1-1-1;P4-2"], {("P1", "1"): ["1"], ("P4", "2"): []}),
        ("P1-1-1;P1-1-2;13+P1-1", {("P1", "1"): ["1", "2"]}),
        (["P12-1"], {("P12", "1"): []}),
        (["6;8-1"], {}),
        (None, {}),
    ],
)
def test_the_articles_of_a_protocol_and_their_paragraphs(
    labels: Any, expected: dict[tuple[str, str], list[str]]
) -> None:
    assert protocol_articles(labels) == expected


def test_a_protocol_is_the_bwb_treaty_the_curated_list_gives_it() -> None:
    treaties = protocol_treaties()
    assert treaties["P1"] == "BWBV0001001"
    assert treaties["P4"] == "BWBV0001029"
    # a Protocol that changes the procedure of the Court is not in it
    assert "P11" not in treaties and "P14" not in treaties
