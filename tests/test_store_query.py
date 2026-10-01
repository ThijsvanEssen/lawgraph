"""ArangoStore.query: the cursor it opens on the server."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

# ── a cursor that is worked on slowly must stay open ─────────────────────────


def test_the_query_cursor_outlives_a_consumer_that_works_on_every_batch() -> None:
    """The server drops a cursor unread for 30 s ("cursor not found"): semantic tk and
    tk-amends failed on it after streaming their documents."""
    from lawgraph.db.store import CURSOR_TTL_SECONDS, ArangoStore

    seen: dict[str, Any] = {}

    class Aql:
        def execute(self, aql, **kwargs):
            seen.update(kwargs)
            return iter([])

    store = ArangoStore.__new__(ArangoStore)
    store.db = SimpleNamespace(aql=Aql())
    store.query("FOR d IN docs RETURN d")

    assert seen["ttl"] == CURSOR_TTL_SECONDS >= 1800
    assert seen["batch_size"] == 1000


def test_a_caller_can_ask_for_a_different_ttl() -> None:
    from lawgraph.db.store import ArangoStore

    seen: dict[str, Any] = {}

    class Aql:
        def execute(self, aql, **kwargs):
            seen.update(kwargs)
            return iter([])

    store = ArangoStore.__new__(ArangoStore)
    store.db = SimpleNamespace(aql=Aql())
    store.query("RETURN 1", ttl=60)
    assert seen["ttl"] == 60
