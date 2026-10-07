"""Answers that are the same for every visitor and change only with the data: kept until
the data version changes (``lg_data_version``, which a write to a table of the graph
raises), and computed once even when many requests ask at the same moment.

On the full graph a facet count over a million judgments, the statistics of the search or
the counts of ``/api/stats`` take seconds to a minute, and the answer is the same until the
next run of the pipelines. The computation runs in a thread of its own, without the
deadline of the request that asked first (a thread of the pool does not inherit it): a
request waits for it no longer than its own deadline, then answers 503, and the
computation goes on for the next. Once the data changed a request waits ``STALE_WAIT`` for
the new answer at most, then takes the last one (of the version before): a facet count or
the statistics of the search minutes old is good, a search that hangs on every write of the
pipelines is not. ``on_new_version`` functions (the API's warm-up) run in
the background when a store shows a version it did not have. A store without
``data_version`` (a fake) keeps nothing.
"""

from __future__ import annotations

import concurrent.futures
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Hashable
from typing import Any, TypeVar

from lawgraph.core.logging import get_logger
from lawgraph.db.store import ReadTimedOut, _text, read_time_left

logger = get_logger(__name__)

T = TypeVar("T")

# The data version is read at most this often (seconds): a run of the pipelines shows within
# it. The tests set it to 0.
VERSION_TTL = 2.0
# Answers kept, the least recently used going first.
MAX_ENTRIES = 4096
# How long a request waits for the answer of a new data version (seconds) before it takes
# the answer of the version before, while the new one goes on computing.
STALE_WAIT = 2.0
# Computations at the same time (each holds a connection of the pool while it reads).
WORKERS = 3

_lock = threading.Lock()
_versions: dict[str, tuple[str | None, float]] = {}  # database -> (version, read at)
_values: OrderedDict[Hashable, Any] = OrderedDict()
_running: dict[Hashable, concurrent.futures.Future[Any]] = {}
# The last answer per (database, key), of whatever version: what a request takes while the
# answer of a new version computes.
_latest: OrderedDict[Hashable, Any] = OrderedDict()
_NONE = object()
_pool = concurrent.futures.ThreadPoolExecutor(
    max_workers=WORKERS, thread_name_prefix="lawgraph-cache"
)
# The warm-up runs apart, one at a time: it waits for computations of the pool above, and
# would hold every worker of it if it ran there.
_warm_pool = concurrent.futures.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="lawgraph-warm"
)
_warmers: list[Callable[[Any], None]] = []


def on_new_version(warm: Callable[[Any], None]) -> None:
    """Run *warm(store)* in the background whenever a store shows a data version this
    process did not know: the answers every visitor asks are then ready before they ask."""
    with _lock:
        _warmers.append(warm)


def warm(store: Any) -> None:
    """Run the ``on_new_version`` functions for *store* now, in the background."""
    with _lock:
        warmers = list(_warmers)
    for function in warmers:
        _warm_pool.submit(_quietly, function, store)


def _quietly(function: Callable[[Any], None], store: Any) -> None:
    try:
        function(store)
    except Exception as exc:  # noqa: BLE001 — a warm-up that fails is asked again later
        logger.warning(
            "Warming %s failed: %s: %s", function.__name__, type(exc).__name__, exc
        )


def _version(store: Any) -> tuple[str, str] | None:
    """``(database, data version)`` of *store*, read at most every ``VERSION_TTL``; None
    when it has none or the database cannot be read. A version this process did not know
    starts the warm-up."""
    read = getattr(store, "data_version", None)
    if read is None:
        return None
    name = str(getattr(store, "name", ""))
    now = time.monotonic()
    with _lock:
        known, read_at = _versions.get(name, (None, float("-inf")))
    if now - read_at >= VERSION_TTL:
        before = known
        try:
            known = read()
        except Exception:  # noqa: BLE001 — without a version nothing is kept
            known = None
        with _lock:
            _versions[name] = (known, now)
        if known and known != before and before is not None:
            warm(store)
    return (name, known) if known else None


def cached(store: Any, key: Hashable, compute: Callable[[], T]) -> T:
    """The answer for *key* of the current data version of *store*: kept, or computed once
    in the background while this request waits for it no longer than its deadline
    (``ReadTimedOut`` then, and the computation goes on). A request that has the answer of
    an earlier version waits ``STALE_WAIT`` at most, then takes that one."""
    version = _version(store)
    if version is None:
        return compute()
    entry_key = (version, key)
    with _lock:
        if entry_key in _values:
            _values.move_to_end(entry_key)
            return _values[entry_key]  # type: ignore[no-any-return]
        future = _running.get(entry_key)
        if future is None:
            future = _pool.submit(_compute, entry_key, compute)
            _running[entry_key] = future
        last = _latest.get((version[0], key), _NONE)
    wait = read_time_left()
    if last is not _NONE and wait is not None:
        # only a request takes an old answer; the warm-up waits for the new one
        wait = min(wait, STALE_WAIT)
    try:
        return future.result(timeout=wait)  # type: ignore[no-any-return]
    except concurrent.futures.TimeoutError as exc:
        if last is not _NONE:
            return last  # type: ignore[return-value]
        raise ReadTimedOut(
            f"The request ran past its deadline waiting for {key!r}, which goes on "
            "computing for the next."
        ) from exc


def _compute(
    entry_key: tuple[tuple[str, str], Hashable], compute: Callable[[], T]
) -> T:
    """Compute and keep one answer (in a thread of the pool: no request deadline, the read
    ceiling alone); a failure is not kept, the next request asks again."""
    try:
        value = compute()
    except BaseException:
        with _lock:
            _running.pop(entry_key, None)
        raise
    (database, _), key = entry_key
    with _lock:
        _values[entry_key] = value
        while len(_values) > MAX_ENTRIES:
            _values.popitem(last=False)
        _latest[(database, key)] = value
        _latest.move_to_end((database, key))
        while len(_latest) > MAX_ENTRIES:
            _latest.popitem(last=False)
        _running.pop(entry_key, None)
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
        _latest.clear()
        _running.clear()


def _frozen(value: Any) -> Hashable:
    if isinstance(value, dict):
        return tuple(sorted((k, _frozen(v)) for k, v in value.items()))
    if isinstance(value, list | tuple | set | frozenset):
        return tuple(_frozen(v) for v in value)
    if isinstance(value, Hashable):
        return value
    return repr(value)
