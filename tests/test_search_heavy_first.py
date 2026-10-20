"""The heavy types of a search take the threads of the pool; the cheap ones run in the
thread of the request meanwhile, so that the slow types overlap instead of adding up."""

from __future__ import annotations

import dataclasses
import threading
from typing import Any

import pytest

from lawgraph.db.queries.search import dispatch
from lawgraph.db.queries.search.spec import SearchType
from lawgraph.db.queries.search.types import SEARCHES
from tests.asserts import show_items
from tests.fakes import PATIENCE

ALL_TYPES = sorted(
    [
        "articles",
        "cabinets",
        "commitments",
        "committees",
        "decisions",
        "documents",
        "dossiers",
        "factions",
        "instruments",
        "judgments",
        "members",
    ]
)


def _recording(threads: dict[str, str]) -> dict[str, SearchType]:
    """The types, each searched by noting the thread it runs in."""
    handed_out = threading.Event()  # the first type run in the caller's own thread

    def run(kind: SearchType, asked: Any, live: bool) -> list[dict[str, Any]]:
        threads[kind.table] = name = threading.current_thread().name
        if name.startswith("search"):
            # a thread of the pool stays busy while the others are handed out
            handed_out.wait(PATIENCE)
        else:
            handed_out.set()
        return [{"key": kind.table, "collection": kind.table, "display_name": "x"}]

    return {t: dataclasses.replace(kind, search=run) for t, kind in SEARCHES.items()}


@pytest.mark.parametrize("entry", ["search_all", "search_full"])
def test_the_heavy_types_go_to_the_pool(
    monkeypatch: pytest.MonkeyPatch, entry: str
) -> None:
    threads: dict[str, str] = {}
    monkeypatch.setattr(dispatch, "notation", lambda *a, **k: None)
    monkeypatch.setattr(dispatch, "SEARCHES", _recording(threads))

    found = getattr(dispatch, entry)(None, q="wet", types=ALL_TYPES)
    hits = found[0] if entry == "search_full" else found

    pooled = {t for t, name in threads.items() if name.startswith("search")}
    assert pooled == {"articles", "judgments", "documents", "instruments"}
    # the answer keeps the order of the types asked for, each with its own hits
    assert list(hits) == ALL_TYPES
    failing = [t for t in ALL_TYPES if hits[t][0]["key"] != t]
    assert not failing, show_items(failing)
