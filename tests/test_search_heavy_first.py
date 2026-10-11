"""The heavy types of a search take the threads of the pool; the cheap ones run in the
thread of the request meanwhile, so that the slow types overlap instead of adding up."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

import pytest

from lawgraph.db.queries import search as search_queries

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


def _recording(threads: dict[str, str]) -> Callable[..., dict[str, Any]]:
    """Searches of every type that note the thread they run in."""

    def searches(*args: Any, **kwargs: Any) -> dict[str, Any]:
        def run(table: str) -> list[dict[str, Any]]:
            threads[table] = threading.current_thread().name
            # a thread of the pool stays busy while the others are handed out
            time.sleep(0.1)
            return [{"key": table, "collection": table, "display_name": table}]

        return {t: (lambda t=t: run(t)) for t in ALL_TYPES}

    return searches


@pytest.mark.parametrize("entry", ["search_all", "search_full"])
def test_the_heavy_types_go_to_the_pool(
    monkeypatch: pytest.MonkeyPatch, entry: str
) -> None:
    threads: dict[str, str] = {}
    monkeypatch.setattr(search_queries, "_notation", lambda *a, **k: None)
    monkeypatch.setattr(search_queries, "_full_searches", _recording(threads))
    monkeypatch.setattr(search_queries, "_live_searches", _recording({}))

    found = getattr(search_queries, entry)(None, q="wet", types=ALL_TYPES)
    hits = found[0] if entry == "search_full" else found

    pooled = {t for t, name in threads.items() if name.startswith("search")}
    assert pooled == {"articles", "judgments", "documents", "instruments"}
    # the answer keeps the order of the types asked for, each with its own hits
    assert list(hits) == ALL_TYPES
    assert all(hits[t][0]["key"] == t for t in ALL_TYPES)
