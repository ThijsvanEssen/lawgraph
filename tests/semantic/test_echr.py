"""The Convention articles an ECHR judgment applies, as HUDOC names them.

The pipeline itself runs against the test server: ``tests/integration/test_echr_convention.py``.
"""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.pipelines.semantic.echr import ECHRSemanticPipeline, convention_articles


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


def test_without_judgments_nothing_is_written() -> None:
    class _Store:
        def query(self, aql: str, bind_vars: dict | None = None) -> list[Any]:
            return []

    assert ECHRSemanticPipeline(store=_Store()).run().created == 0
