"""The answers of ``lasting`` are bounded like those of ``cached``: each unique search or
filter adds a key, and an API process lives from deploy to deploy."""

from __future__ import annotations

from collections.abc import Iterable

import pytest

from lawgraph.db import version_cache


class _Store:
    name = "bounded"

    def data_version(self, tables: Iterable[str] | None = None) -> str:
        return "1"


def test_the_least_recently_used_lasting_answer_goes_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(version_cache, "MAX_ENTRIES", 3)
    store = _Store()
    computed: list[str] = []

    def ask(key: str) -> str:
        def compute() -> str:
            computed.append(key)
            return key

        return version_cache.lasting(store, (key,), compute, 3600, inline=True)

    for key in ("a", "b", "c"):
        ask(key)
    ask("a")  # read: "b" is now the least recently used
    ask("d")
    assert len(version_cache._lasting) == 3
    computed.clear()
    for key in ("a", "c", "d"):
        ask(key)
    assert computed == []
    ask("b")
    assert computed == ["b"]


def test_a_lasting_answer_computed_on_the_pool_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(version_cache, "MAX_ENTRIES", 2)
    store = _Store()
    for key in ("a", "b", "c"):
        assert version_cache.lasting(store, (key,), lambda k=key: k, 3600) == key
    assert len(version_cache._lasting) == 2
