"""The dossiers of a faction, asked by many requests at once (threads of the pool)."""

from __future__ import annotations

import threading
from collections.abc import Iterable
from typing import Any

import pytest

from lawgraph.api.routes import factions as faction_routes
from lawgraph.db import version_cache
from tests.fakes import InMemoryStore


class _VersionedStore(InMemoryStore):
    """One data version: what the cache keeps it keeps."""

    name = "fake"

    def data_version(self, tables: Iterable[str] | None = None) -> str:
        return "1"


def test_eight_threads_on_a_cache_of_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each thread its own page, side by side, while every answer kept evicts the one
    before: each gets its own page, none an error (a cache that marked a key used after
    another thread evicted it raised ``KeyError``, a 500)."""
    monkeypatch.setattr(
        faction_routes,
        "actor_dossiers",
        lambda store, actor, limit, offset: (actor, limit, offset),
    )
    monkeypatch.setattr(version_cache, "MAX_ENTRIES", 1)
    store: Any = _VersionedStore(
        {"factions": [{"id": "factions/vvd", "key": "vvd", "type": "faction",
                       "labels": [], "props": {}}]}
    )  # fmt: skip
    start = threading.Barrier(8)
    errors: list[BaseException] = []
    answers: dict[int, list[Any]] = {}

    def ask(n: int) -> None:
        try:
            start.wait(5)
            answers[n] = [
                faction_routes.list_faction_dossiers("vvd", store, 10, n)
                for _ in range(20)
            ]
        except BaseException as exc:  # noqa: BLE001 — what the request would 500 on
            errors.append(exc)

    threads = [threading.Thread(target=ask, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert not errors
    assert answers == {n: [("factions/vvd", 10, n)] * 20 for n in range(8)}
