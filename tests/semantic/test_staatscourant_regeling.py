"""The queries of semantic staatscourant: one match per publication, found through an index."""

from __future__ import annotations

import re
from typing import Any

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
