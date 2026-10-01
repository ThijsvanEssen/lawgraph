"""semantic staatscourant: the date it passes on, and a failing query that ends the step.

What the matching queries return (one match per publication, the date of a publication
compared as a date) is tested against the test server:
``tests/integration/test_staatscourant_matches.py``.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from lawgraph.db.queries.semantic import bwb as semantic_bwb
from lawgraph.pipelines.semantic.staatscourant import (
    StaatscourantSemanticPipeline,
)


def test_since_is_passed_on_as_the_date_of_the_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """props.date is "2026-09-19"; a timestamp of that day sorts after it and misses it."""
    asked: list[tuple[str, str | None]] = []

    def matches(store: Any, since_date: str | None) -> list[dict]:
        asked.append(("matches", since_date))
        return []

    def texts(store: Any, since_date: str | None) -> list[dict]:
        asked.append(("texts", since_date))
        return []

    monkeypatch.setattr(semantic_bwb, "staatscourant_instrument_matches", matches)
    monkeypatch.setattr(semantic_bwb, "staatscourant_texts", texts)

    since = dt.datetime(2026, 9, 19, 6, 0, tzinfo=dt.timezone.utc)
    StaatscourantSemanticPipeline(store=object()).run(since=since)

    assert asked == [("matches", "2026-09-19"), ("texts", "2026-09-19")]


def test_a_failing_query_ends_the_step_instead_of_leaving_its_edges_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing(store: Any, since_date: str | None) -> list[dict]:
        raise RuntimeError("memory limit exceeded")

    monkeypatch.setattr(semantic_bwb, "staatscourant_instrument_matches", failing)

    with pytest.raises(RuntimeError, match="memory limit exceeded"):
        StaatscourantSemanticPipeline(store=object()).run()
