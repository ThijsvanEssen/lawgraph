"""The queries of semantic staatscourant: one match per publication, found through an index."""

from __future__ import annotations

import re
from typing import Any

import pytest

from lawgraph.pipelines.semantic.staatscourant_regeling import (
    StaatscourantRegelingSemanticPipeline,
)


class _Store:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def query(self, aql: str, bind_vars: dict | None = None, **_kw: Any) -> list[dict]:
        self.queries.append(aql)
        return []


def _queries() -> list[str]:
    store = _Store()
    StaatscourantRegelingSemanticPipeline(store=store).run()
    return store.queries


def test_limit_one_is_per_publication_not_for_the_whole_query() -> None:
    """``FOR pub ... FOR inst ... LIMIT 1`` returns one row in total; it belongs in a subquery."""
    limited = [aql for aql in _queries() if "LIMIT 1" in aql]
    assert len(limited) == 2  # by bwb_id and by title
    for aql in limited:
        assert re.search(
            r"LET inst = FIRST\(\s*FOR i IN .*?LIMIT 1\s*RETURN i\s*\)", aql, re.S
        )
        assert aql.count("LIMIT 1") == 1


def test_a_bwb_id_is_compared_as_stored_so_its_index_is_used() -> None:
    for aql in _queries():
        assert "UPPER(" not in aql or "bwb_id" not in aql.split("UPPER(", 1)[1][:20]


def test_since_is_compared_as_a_date_with_the_date_of_the_publication() -> None:
    """props.date is "2026-09-19"; a timestamp of that day sorts after it and misses it."""
    import datetime as dt

    class Binds(_Store):
        def __init__(self) -> None:
            super().__init__()
            self.binds: list[dict] = []

        def query(
            self, aql: str, bind_vars: dict | None = None, **_kw: Any
        ) -> list[dict]:
            self.binds.append(dict(bind_vars or {}))
            return []

    store = Binds()
    since = dt.datetime(2026, 9, 19, 6, 0, tzinfo=dt.timezone.utc)
    StaatscourantRegelingSemanticPipeline(store=store).run(since=since)
    assert {b["since_iso"] for b in store.binds if "since_iso" in b} == {"2026-09-19"}


def test_a_failing_query_ends_the_step_instead_of_leaving_its_edges_out() -> None:
    class Failing(_Store):
        def query(
            self, aql: str, bind_vars: dict | None = None, **_kw: Any
        ) -> list[dict]:
            if "match_type: 'title'" in aql:
                raise RuntimeError("memory limit exceeded")
            return []

    with pytest.raises(RuntimeError, match="memory limit exceeded"):
        StaatscourantRegelingSemanticPipeline(store=Failing()).run()
