"""The dossiers of a faction, asked by many requests at once (threads of the pool)."""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any

import pytest

from lawgraph.api.routes import committees as committee_routes
from lawgraph.core.cache import TTLCache
from lawgraph.core.models import Node, NodeType


class _Store:
    name = "fake"

    def get_node(self, collection: str, key: str) -> Any:
        return Node(collection=collection, type=NodeType.FACTION, key=key,
                    _skip_validation=True)  # fmt: skip


class _Interleaving(OrderedDict[Any, Any]):
    """Lets thread 0 stop between finding its key and marking it used, while the
    others store theirs."""

    def __init__(self, found: threading.Event, stored: threading.Event) -> None:
        super().__init__()
        self.found, self.stored = found, stored

    def get(self, key: Any, default: Any = None) -> Any:
        value = super().get(key, default)
        if value is not None and threading.current_thread().name == "asker-0":
            self.found.set()
            self.stored.wait(5)
        return value


def test_eight_threads_on_a_cache_of_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        committee_routes,
        "_actor_dossiers",
        lambda store, actor, limit, offset: (actor, limit, offset),
    )
    cache: TTLCache[Any, Any] = TTLCache(maxsize=1)
    found, stored = threading.Event(), threading.Event()
    cache._store = _Interleaving(found, stored)
    monkeypatch.setattr(committee_routes, "_faction_dossiers_cache", cache)
    store = _Store()
    committee_routes.list_faction_dossiers("vvd", store, 10, 0)  # type: ignore[arg-type]

    errors: list[BaseException] = []
    answers: dict[int, Any] = {}

    def ask(n: int) -> None:
        try:
            if n:
                found.wait(5)
            answers[n] = committee_routes.list_faction_dossiers(
                "vvd",
                store,
                10,
                n,  # type: ignore[arg-type]
            )
        except BaseException as exc:  # noqa: BLE001 — what the request would 500 on
            errors.append(exc)
        finally:
            if n:
                stored.set()

    threads = [threading.Thread(target=ask, args=(n,), name=f"asker-{n}")
               for n in range(8)]  # fmt: skip
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert not errors
    assert answers == {n: ("factions/vvd", 10, n) for n in range(8)}
