"""Answers that are the same for every visitor and change only with the data: kept until
the data version changes (``lg_data_version``, which a write to a table of the graph
raises), and computed once even when many requests ask at the same moment.

On the full graph a facet count over a million judgments, the statistics of the search or
the counts of ``/api/stats`` take seconds to a minute, and the answer is the same until the
next run of the pipelines. A store without ``data_version`` (a fake) caches nothing.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Hashable
from typing import Any, TypeVar

from lawgraph.db.store import _text

T = TypeVar("T")

# The data version is read at most this often (seconds): a run of the pipelines shows within
# it. The tests set it to 0.
VERSION_TTL = 2.0
# Answers kept, the least recently used going first.
MAX_ENTRIES = 4096

_lock = threading.Lock()
_versions: dict[str, tuple[str | None, float]] = {}  # database -> (version, read at)
_values: OrderedDict[Hashable, tuple[Hashable, Any]] = OrderedDict()
_computing: dict[Hashable, threading.Lock] = {}


def _version(store: Any) -> Hashable | None:
    """``(database, data version)`` of *store*, read at most every ``VERSION_TTL``; None
    when it has none or the database cannot be read."""
    read = getattr(store, "data_version", None)
    if read is None:
        return None
    name = str(getattr(store, "name", ""))
    now = time.monotonic()
    with _lock:
        known, read_at = _versions.get(name, (None, float("-inf")))
    if now - read_at >= VERSION_TTL:
        try:
            known = read()
        except Exception:  # noqa: BLE001 — without a version nothing is kept
            known = None
        with _lock:
            _versions[name] = (known, now)
    return (name, known) if known else None


def cached(store: Any, key: Hashable, compute: Callable[[], T]) -> T:
    """The answer for *key* of the current data version of *store*: kept, or computed (once,
    whoever else asks for it meanwhile waits for it)."""
    version = _version(store)
    if version is None:
        return compute()
    entry_key = (version, key)
    with _lock:
        found = _values.get(entry_key)
        if found is not None:
            _values.move_to_end(entry_key)
            return found[1]  # type: ignore[no-any-return]
        computing = _computing.setdefault(entry_key, threading.Lock())
    with computing:
        with _lock:
            found = _values.get(entry_key)
        if found is not None:
            return found[1]  # type: ignore[no-any-return]
        value = compute()
        with _lock:
            _values[entry_key] = (version, value)
            while len(_values) > MAX_ENTRIES:
                _values.popitem(last=False)
            _computing.pop(entry_key, None)
    return value


def cached_rows(
    store: Any, statement: Any, params: dict[str, Any] | None = None, **options: Any
) -> list[Any]:
    """The rows of *statement* with *params*, kept per data version: for a count or a
    facet that every visitor asks the same."""
    key = (
        "rows",
        _text(statement),
        _frozen(params or {}),
        tuple(sorted(options.items())),
    )
    return cached(store, key, lambda: list(store.query(statement, params, **options)))


def clear() -> None:
    """Forget every kept answer (the tests)."""
    with _lock:
        _versions.clear()
        _values.clear()
        _computing.clear()


def _frozen(value: Any) -> Hashable:
    if isinstance(value, dict):
        return tuple(sorted((k, _frozen(v)) for k, v in value.items()))
    if isinstance(value, list | tuple | set | frozenset):
        return tuple(_frozen(v) for v in value)
    if isinstance(value, Hashable):
        return value
    return repr(value)
