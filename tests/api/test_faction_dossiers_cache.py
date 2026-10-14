"""The dossiers of a faction, asked by many requests at once (threads of the pool)."""

from __future__ import annotations

import threading
from typing import Any

import pytest

from lawgraph.api.routes import committees as committee_routes
from lawgraph.db import version_cache


class _Store:
    name = "fake"

    def data_version(self) -> str:
        return "1"

    def get_document(self, collection: str, key: str) -> Any:
        return {"_id": f"{collection}/{key}", "_key": key, "type": "faction",
                "labels": [], "props": {}}  # fmt: skip


def test_eight_threads_on_a_cache_of_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each thread its own page, side by side, while every answer kept evicts the one
    before: each gets its own page, none an error (a cache that marked a key used after
    another thread evicted it raised ``KeyError``, a 500)."""
    monkeypatch.setattr(
        committee_routes,
        "_actor_dossiers",
        lambda store, actor, limit, offset: (actor, limit, offset),
    )
    monkeypatch.setattr(version_cache, "MAX_ENTRIES", 1)
    store: Any = _Store()
    start = threading.Barrier(8)
    errors: list[BaseException] = []
    answers: dict[int, list[Any]] = {}

    def ask(n: int) -> None:
        try:
            start.wait(5)
            answers[n] = [
                committee_routes.list_faction_dossiers("vvd", store, 10, n)
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
