"""A state that only ever comes to hold, known without asking once it holds
(``version_cache.once_true``): the readiness of the side tables a request reads."""

from __future__ import annotations

from types import SimpleNamespace

from lawgraph.db import version_cache


def test_a_true_is_kept_and_a_false_is_asked_again() -> None:
    store = SimpleNamespace(name="db_a")
    answers = [False, True, False]
    asked: list[bool] = []

    def check() -> bool:
        asked.append(True)
        return answers[len(asked) - 1]

    assert version_cache.once_true(store, "filled", check) is False
    assert version_cache.once_true(store, "filled", check) is True  # asked again
    assert version_cache.once_true(store, "filled", check) is True  # kept: not asked
    assert len(asked) == 2


def test_kept_per_database_and_forgotten_by_clear() -> None:
    a, b = SimpleNamespace(name="db_a"), SimpleNamespace(name="db_b")
    assert version_cache.once_true(a, "filled", lambda: True) is True
    assert version_cache.once_true(b, "filled", lambda: False) is False
    version_cache.clear()
    assert version_cache.once_true(a, "filled", lambda: False) is False
